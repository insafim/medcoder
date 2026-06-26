"""Per-agent model resolution + provider-aware sampling predicates.

These are pure, deterministic functions (no LLM, no network), so they are unit
tested directly. They guard two behaviours that are easy to regress silently:
  - which model each agent resolves to (per-agent override vs shared fallback);
  - which models must NOT be sent a custom ``temperature`` (reasoning models).
"""

from __future__ import annotations

from pydantic import BaseModel

import medcoder.llm as llm_mod
from medcoder.config import Settings, get_settings
from medcoder.llm import _is_openai_gpt5, _rejects_custom_temperature

# ----- Settings.model_for -------------------------------------------------


def _settings(**overrides) -> Settings:
    """Build Settings with explicit values (init kwargs beat .env/env/defaults)."""
    base = {
        "llm_model": "openai/gpt-5.4-mini",
        "extraction_model": None,
        "coder_model": None,
        "verifier_model": "anthropic/claude-haiku-4-5-20251001",
    }
    base.update(overrides)
    return Settings(**base)


def test_model_for_falls_back_to_shared_llm_model():
    s = _settings()
    assert s.model_for("extraction") == "openai/gpt-5.4-mini"
    assert s.model_for("coder") == "openai/gpt-5.4-mini"


def test_model_for_honours_per_agent_overrides():
    s = _settings(
        extraction_model="openai/gpt-5.4-nano",
        coder_model="openai/gpt-5.4-mini",
    )
    assert s.model_for("extraction") == "openai/gpt-5.4-nano"
    assert s.model_for("coder") == "openai/gpt-5.4-mini"


def test_model_for_auditor_uses_verifier_model():
    s = _settings(verifier_model="anthropic/claude-sonnet-4-6")
    assert s.model_for("auditor") == "anthropic/claude-sonnet-4-6"


def test_model_for_unknown_agent_falls_back_to_llm_model():
    s = _settings()
    assert s.model_for("nonexistent") == "openai/gpt-5.4-mini"


# ----- config_hash sensitivity --------------------------------------------


def test_config_hash_changes_with_per_agent_model():
    a = _settings().config_hash()
    b = _settings(extraction_model="openai/gpt-5.4-nano").config_hash()
    assert a != b


def test_config_hash_changes_with_reasoning_effort():
    a = _settings(reasoning_effort="low").config_hash()
    b = _settings(reasoning_effort="high").config_hash()
    assert a != b


def test_config_hash_is_stable_for_identical_settings():
    assert _settings().config_hash() == _settings().config_hash()


# ----- _is_openai_gpt5 ----------------------------------------------------


def test_is_openai_gpt5_true_for_gpt5_family():
    assert _is_openai_gpt5("openai/gpt-5.4-mini")
    assert _is_openai_gpt5("openai/gpt-5.4-nano")
    assert _is_openai_gpt5("gpt-5.5")


def test_is_openai_gpt5_false_for_others():
    assert not _is_openai_gpt5("openai/gpt-4o-2024-08-06")
    assert not _is_openai_gpt5("anthropic/claude-haiku-4-5-20251001")


# ----- _rejects_custom_temperature ----------------------------------------


def test_rejects_temperature_for_gpt5_family():
    assert _rejects_custom_temperature("openai/gpt-5.4-mini")
    assert _rejects_custom_temperature("openai/gpt-5.4-nano")
    assert _rejects_custom_temperature("gpt-5.5")


def test_rejects_temperature_for_claude_opus_4_7_plus():
    assert _rejects_custom_temperature("anthropic/claude-opus-4-7")
    assert _rejects_custom_temperature("anthropic/claude-opus-4-8")


def test_allows_temperature_for_non_reasoning_models():
    # gpt-4o, current Claude Haiku/Sonnet, and older Opus all honour temperature.
    assert not _rejects_custom_temperature("openai/gpt-4o-2024-08-06")
    assert not _rejects_custom_temperature("anthropic/claude-haiku-4-5-20251001")
    assert not _rejects_custom_temperature("anthropic/claude-sonnet-4-6")
    assert not _rejects_custom_temperature("anthropic/claude-opus-4-6-20260205")


# ----- call_structured assembles the right provider kwargs ----------------


class _Tiny(BaseModel):
    ok: bool


def _captured_kwargs(monkeypatch, model: str) -> dict:
    """Run call_structured with the provider call stubbed; return the kwargs it built.

    Directly verifies the guard that prevents 400s — that `temperature` is omitted
    (and `reasoning_effort` added) for reasoning models — rather than relying on
    indirect mocked-pipeline coverage.
    """
    captured: dict = {}

    class _Msg:
        content = '{"ok": true}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = None

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr(llm_mod, "completion", fake_completion)
    llm_mod.call_structured(
        agent="coder",
        system_prompt="s",
        user_prompt="u",
        schema=_Tiny,
        model=model,
        use_cache=False,
    )
    return captured


def test_call_structured_omits_temperature_for_gpt5(monkeypatch):
    kw = _captured_kwargs(monkeypatch, "openai/gpt-5.4-mini")
    assert "temperature" not in kw  # the 400-prevention guard
    assert kw.get("reasoning_effort") == get_settings().reasoning_effort


def test_call_structured_sends_temperature_for_claude_haiku(monkeypatch):
    kw = _captured_kwargs(monkeypatch, "anthropic/claude-haiku-4-5-20251001")
    assert kw.get("temperature") == get_settings().temperature
    assert "reasoning_effort" not in kw
