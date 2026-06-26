"""Retry-policy tests for the LLM gateway (`medcoder.llm`).

These pin the behaviour of ``_RETRYABLE_LLM_ERRORS``: transient provider errors
(rate limits, timeouts, upstream 5xx) are retried with back-off, while
non-transient errors (auth, bad-request) fail fast so the pipeline's per-stage
handler can degrade immediately instead of burning seconds of pointless retries.
"""

from __future__ import annotations

import litellm
import pytest
from pydantic import BaseModel

import medcoder.llm as llm


class _Tiny(BaseModel):
    x: int


def _kwargs(model: str = "openai/gpt-5.4-mini") -> dict:
    # use_cache=False so we always hit the (mocked) provider call, never the cache.
    return dict(
        agent="t",
        system_prompt="s",
        user_prompt="u",
        schema=_Tiny,
        model=model,
        use_cache=False,
    )


# The transient set the gateway retries. Hard-coded (NOT imported from
# llm._RETRYABLE_LLM_ERRORS) so that removing a type from the source tuple makes
# the matching case here fail — its call count would drop to 1.
_TRANSIENT_ERRORS = [
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.InternalServerError,
    litellm.BadGatewayError,
    litellm.ServiceUnavailableError,
]


@pytest.mark.parametrize("exc_type", _TRANSIENT_ERRORS, ids=lambda e: e.__name__)
def test_transient_error_is_retried(monkeypatch, exc_type):
    """Each transient error is attempted 3 times (1 initial + 2 retries) before LLMError."""
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)  # collapse tenacity back-off
    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        raise exc_type("transient", llm_provider="openai", model="openai/gpt-5.4-mini")

    monkeypatch.setattr(llm, "completion", boom)
    with pytest.raises(llm.LLMError):
        llm.call_structured(**_kwargs())
    assert calls["n"] == 3  # 1 initial attempt + 2 retries


def test_auth_error_is_not_retried(monkeypatch):
    """An unfunded/invalid key (auth error) must fail on the first attempt."""
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        raise litellm.AuthenticationError(
            "no credits", llm_provider="anthropic", model="anthropic/claude-haiku-4-5-20251001"
        )

    monkeypatch.setattr(llm, "completion", boom)
    with pytest.raises(llm.LLMError):
        llm.call_structured(**_kwargs(model="anthropic/claude-haiku-4-5-20251001"))
    assert calls["n"] == 1  # failed fast — no wasted back-off


def test_bad_request_is_not_retried(monkeypatch):
    """A 400 (e.g. malformed request / bad model) is non-transient → no retry."""
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    calls = {"n": 0}

    def boom(**kwargs):
        calls["n"] += 1
        raise litellm.BadRequestError(
            "bad request", model="openai/gpt-5.4-mini", llm_provider="openai"
        )

    monkeypatch.setattr(llm, "completion", boom)
    with pytest.raises(llm.LLMError):
        llm.call_structured(**_kwargs())
    assert calls["n"] == 1
