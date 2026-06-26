"""LiteLLM gateway with structured output, validate→repair, caching, and cost capture.

One entry point: :func:`call_structured` — given a Pydantic schema, returns a
validated instance. Backed by LiteLLM so we get OpenAI / Anthropic / Gemini /
Bedrock / local in one call, plus built-in `mock_response` for tests.

Design notes (Plan.md §13):
- *reason-then-format*: prompts instruct the model to think first then emit JSON.
  Strict JSON-only output is enforced via LiteLLM's response_format=PydanticModel.
- *validate→repair-retry*: on schema failure we re-ask the model with the
  validation error appended (one retry by default).
- *cache*: deterministic input → on-disk cached response (~free reproducibility).
- *cost*: `litellm.completion_cost` invoked on every response; accumulated into
  the run's `RunMetrics`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import litellm
from litellm import completion, completion_cost
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import get_settings
from .logging_setup import get_logger

log = get_logger(__name__)

# Silence LiteLLM's chatty debug output; keep warnings/errors.
litellm.suppress_debug_info = True

T = TypeVar("T", bound=BaseModel)


# ----- model pricing + capability predicates ------------------------------

# Published list prices (USD per 1M tokens) as of 2026-06-26. Registered with
# LiteLLM so `completion_cost` stays accurate for model IDs newer than LiteLLM's
# bundled cost map (the newest Claude/GPT-5.4 IDs may not be in it yet).
# Sources: https://developers.openai.com/api/docs/pricing             (verified live 2026-06-26)
#          https://platform.claude.com/docs/en/about-claude/pricing   (verified live 2026-06-26)
_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}


def _register_model_prices() -> None:
    """Best-effort registration of current prices into LiteLLM's cost map.

    We register both the bare ID and the provider-prefixed form so a lookup keyed
    by either resolves. Failure is non-fatal — cost capture is already wrapped in
    a try/except at the call site and degrades to 0.0.
    """
    cost_map: dict[str, dict[str, Any]] = {}
    for name, (inp, outp) in _PRICES_PER_1M.items():
        provider = "openai" if name.startswith("gpt") else "anthropic"
        entry = {
            "input_cost_per_token": inp / 1_000_000,
            "output_cost_per_token": outp / 1_000_000,
            "litellm_provider": provider,
            "mode": "chat",
        }
        cost_map[name] = entry
        cost_map[f"{provider}/{name}"] = entry
    try:
        litellm.register_model(cost_map)
    except Exception:  # noqa: BLE001  cost registration is best-effort
        log.debug("model_price_registration_failed")


_register_model_prices()


def _is_openai_gpt5(model: str) -> bool:
    """True for the OpenAI GPT-5 family (gpt-5, gpt-5.4-mini, gpt-5.5, …)."""
    m = model.lower()
    return m.startswith(("openai/gpt-5", "gpt-5"))


def _rejects_custom_temperature(model: str) -> bool:
    """Models that return a 400 on a non-default ``temperature``.

    - OpenAI GPT-5 family (reasoning models) accept only the default temperature
      and expose ``reasoning_effort`` instead.
      Source: https://developers.openai.com/api/docs/guides/reasoning   (verified live 2026-06-26)
    - Anthropic Claude Opus 4.7+ rejects non-default temperature/top_p/top_k.
      Source: https://platform.claude.com/docs/en/about-claude/model-deprecations  (verified live 2026-06-26)
    """
    m = model.lower()
    if _is_openai_gpt5(m):
        return True
    opus = re.search(r"claude-opus-4-(\d+)", m)
    return bool(opus and int(opus.group(1)) >= 7)


class LLMError(RuntimeError):
    """Raised when an LLM call fails after retries or its output can't be validated."""


@dataclass
class CallStats:
    """Per-call accounting; the pipeline aggregates these into RunMetrics."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    retries: int = 0
    cached: bool = False


@dataclass
class CallAggregator:
    """Cheap collector — pipeline owns one of these per run."""

    by_agent: dict[str, dict[str, int]] = field(default_factory=dict)
    cost_usd: float = 0.0
    retries: int = 0

    def add(self, agent: str, stats: CallStats) -> None:
        b = self.by_agent.setdefault(
            agent, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
        )
        b["prompt_tokens"] += stats.prompt_tokens
        b["completion_tokens"] += stats.completion_tokens
        b["total_tokens"] += stats.total_tokens
        b["calls"] += 1
        self.cost_usd += stats.cost_usd
        self.retries += stats.retries

    def token_totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for agent, b in self.by_agent.items():
            for k, v in b.items():
                out[f"{agent}.{k}"] = v
        return out


# ----- cache --------------------------------------------------------------


def _cache_key(model: str, messages: list[dict[str, Any]], schema_name: str) -> str:
    blob = json.dumps(
        {"model": model, "messages": messages, "schema": schema_name},
        sort_keys=True,
        default=str,
    ).encode()
    return hashlib.sha256(blob).hexdigest()


def _cache_get(cache_dir: Path, key: str) -> dict[str, Any] | None:
    p = cache_dir / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _cache_put(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{key}.json").write_text(json.dumps(payload))


# ----- core call ----------------------------------------------------------


def _build_messages(system: str, user: str, schema: type[BaseModel]) -> list[dict[str, str]]:
    schema_hint = (
        "Return ONLY a JSON object matching this Pydantic schema "
        f"(name={schema.__name__}). Reason internally first, then emit the JSON. "
        "Do not include markdown fences or commentary outside the JSON."
    )
    return [
        {"role": "system", "content": f"{system}\n\n{schema_hint}"},
        {"role": "user", "content": user},
    ]


# Retry ONLY on transient provider errors — rate limits (429), timeouts, upstream
# 5xx (500/502/503), and network blips. Non-transient failures (auth, 400 bad-request,
# 404 bad model, context-window) cannot succeed on a retry, so we fail fast and let the
# pipeline's per-stage handler degrade immediately rather than burn ~7s of
# back-off (this is what makes an unfunded auditor key degrade quickly, not slowly).
# LiteLLM exposes a typed exception hierarchy mirroring OpenAI's.
# Sources: https://docs.litellm.ai/docs/exception_mapping   (verified 2026-06-26)
#          https://tenacity.readthedocs.io/en/latest/       (verified 2026-06-26)
_RETRYABLE_LLM_ERRORS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.InternalServerError,  # HTTP 500
    litellm.BadGatewayError,  # HTTP 502
    litellm.ServiceUnavailableError,  # HTTP 503
)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(_RETRYABLE_LLM_ERRORS),
)
def _raw_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_format: type[BaseModel] | dict[str, Any],
    temperature: float | None,
    reasoning_effort: str | None,
    max_tokens: int,
    mock_response: str | None,
) -> Any:
    """Single call into ``litellm.completion`` (the only provider call site).

    Param convention: ``temperature`` and ``reasoning_effort`` are ``None`` to mean
    "omit this field entirely" — required because reasoning models (GPT-5,
    Claude Opus 4.7+) 400 on a non-default temperature, and ``reasoning_effort`` is
    only meaningful for OpenAI GPT-5. The caller (`call_structured`) decides which to
    send via `_rejects_custom_temperature` / `_is_openai_gpt5`.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": response_format,
    }
    # `temperature` is omitted for models that reject a non-default value
    # (GPT-5 family, Claude Opus 4.7+); `reasoning_effort` is sent only to GPT-5.
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if mock_response is not None:
        kwargs["mock_response"] = mock_response
    return completion(**kwargs)


def call_structured(
    *,
    agent: str,
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    model: str | None = None,
    aggregator: CallAggregator | None = None,
    mock_response: str | None = None,
    use_cache: bool = True,
) -> T:
    """Call an LLM and return a validated `schema` instance.

    `mock_response` is a JSON string the LLM returns verbatim — used by tests so
    no API key is required. When set, no caching is performed.
    """
    settings = get_settings()
    # Callers resolve their per-agent model via Settings.model_for(...) and pass it
    # explicitly. This fallback is a safety net only: an omitted model uses the shared
    # `llm_model` and therefore does NOT pick up extraction_model/coder_model overrides.
    model = model or settings.llm_model
    stats = CallStats(model=model)

    messages = _build_messages(system_prompt, user_prompt, schema)
    cache_key = _cache_key(model, messages, schema.__name__)

    if mock_response is None and use_cache:
        cached = _cache_get(settings.cache_dir, cache_key)
        if cached is not None:
            try:
                obj = schema.model_validate(cached["payload"])
                stats.cached = True
                stats.prompt_tokens = cached.get("prompt_tokens", 0)
                stats.completion_tokens = cached.get("completion_tokens", 0)
                stats.total_tokens = cached.get("total_tokens", 0)
                if aggregator is not None:
                    aggregator.add(agent, stats)
                log.info("llm_cache_hit", extra={"agent": agent, "model": model})
                return obj
            except ValidationError:
                # Stale cache shape — fall through to re-call.
                pass

    # Provider-aware sampling params: reasoning models (GPT-5, Claude Opus 4.7+)
    # reject a custom temperature; GPT-5 takes reasoning_effort instead.
    if _rejects_custom_temperature(model):
        call_temperature: float | None = None
        call_reasoning_effort = settings.reasoning_effort if _is_openai_gpt5(model) else None
    else:
        call_temperature = settings.temperature
        call_reasoning_effort = None

    last_err: Exception | None = None
    raw_text = ""
    for attempt in range(2):  # initial + 1 repair retry
        try:
            resp = _raw_completion(
                model=model,
                messages=messages,
                response_format=schema,
                temperature=call_temperature,
                reasoning_effort=call_reasoning_effort,
                max_tokens=settings.max_tokens,
                mock_response=mock_response,
            )
        except Exception as e:
            stats.retries += 1
            last_err = e
            log.warning("llm_call_failed", extra={"agent": agent, "model": model, "error": str(e)})
            raise LLMError(f"{agent} call failed: {e}") from e

        choice = resp.choices[0].message
        raw_text = (choice.content or "").strip()
        try:
            obj = schema.model_validate_json(raw_text)
            usage = getattr(resp, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                stats.total_tokens = getattr(usage, "total_tokens", 0) or 0
            try:
                stats.cost_usd = float(completion_cost(completion_response=resp) or 0.0)
            except Exception:  # noqa: BLE001  cost lookup is best-effort
                stats.cost_usd = 0.0

            if mock_response is None and use_cache:
                _cache_put(
                    settings.cache_dir,
                    cache_key,
                    {
                        "payload": json.loads(raw_text),
                        "prompt_tokens": stats.prompt_tokens,
                        "completion_tokens": stats.completion_tokens,
                        "total_tokens": stats.total_tokens,
                    },
                )
            if aggregator is not None:
                aggregator.add(agent, stats)
            return obj
        except (ValidationError, json.JSONDecodeError) as e:
            last_err = e
            stats.retries += 1
            log.warning(
                "llm_validation_failed",
                extra={"agent": agent, "attempt": attempt, "error": str(e)[:300]},
            )
            messages = messages + [
                {"role": "assistant", "content": raw_text},
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed schema validation with this error:\n"
                        f"{e}\n\n"
                        "Please return ONLY valid JSON matching the schema. No fences, no prose."
                    ),
                },
            ]

    raise LLMError(f"{agent} produced unparseable output after retries: {last_err}")


# ----- env helpers --------------------------------------------------------


def have_api_key_for(model: str) -> bool:
    """Quick local check — does the env have a key for this model's provider?

    Conservative: returns True only when we recognise the provider prefix.
    Used by the CLI to suggest `--mock` instead of crashing on a 401.
    """
    m = model.lower()
    if m.startswith(("openai/", "gpt", "chatgpt")):
        return bool(os.environ.get("OPENAI_API_KEY"))
    if m.startswith(("anthropic/", "claude")):
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if m.startswith(("gemini/", "google/", "gemini")):
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if m.startswith(("bedrock/", "anthropic.")):
        return bool(os.environ.get("AWS_ACCESS_KEY_ID"))
    # Unknown provider — assume user knows what they're doing.
    return True


def downgrade_logger_for_tests() -> None:
    """Silence litellm during pytest runs."""
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
