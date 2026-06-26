"""Runtime configuration — environment-driven via pydantic-settings.

Everything reproducibility-relevant (model snapshots, temperature, thresholds,
embedder, catalog paths) is captured here so a single config_hash fingerprints a
run end-to-end.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PIPELINE_VERSION = "0.1.0"
PROMPT_VERSION = "p1"

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MEDCODER_",
        extra="ignore",
    )

    # --- Models (current generation; cost-optimised; cross-family auditor) ---
    # LiteLLM model strings: use provider-prefixed form so the gateway doesn't have to
    # guess the provider (recent LiteLLM versions stopped inferring it from "claude-…").
    #
    # Per-agent override: MEDCODER_EXTRACTION_MODEL / MEDCODER_CODER_MODEL fall back to
    # MEDCODER_LLM_MODEL when unset; the auditor uses MEDCODER_VERIFIER_MODEL. This lets
    # cost be tuned per role (e.g. drop extraction to the cheaper nano tier). Defaults
    # verified current 2026-06-26; the prior gpt-4o / claude-3-5 snapshots are
    # superseded (and the claude-3-5 IDs are now retired by Anthropic).
    llm_model: str = Field(
        "openai/gpt-5.4-mini",
        description="Shared default for extraction + coder (balanced cost/quality)",
    )
    extraction_model: str | None = Field(
        None, description="Override for the extraction agent; falls back to llm_model"
    )
    coder_model: str | None = Field(
        None, description="Override for the coder agent; falls back to llm_model"
    )
    verifier_model: str = Field(
        "anthropic/claude-haiku-4-5-20251001",
        description="Independent auditor — cheapest current Claude, a different family",
    )
    # OpenAI GPT-5 are reasoning models: they reject a non-default `temperature` and
    # expose `reasoning_effort` instead. We keep temperature=0 for providers that honour
    # it (Claude Haiku/Sonnet) and pass reasoning_effort to GPT-5 to bound reasoning cost.
    temperature: float = 0.0
    reasoning_effort: str = Field(
        "low", description="OpenAI GPT-5 reasoning effort (none|low|medium|high); bounds cost"
    )
    max_tokens: int = 1500

    # --- Retrieval -------------------------------------------------------
    embedder: str = "sentence-transformers/all-MiniLM-L6-v2"
    retrieval_top_k: int = 15
    retrieval_dense_n: int = 50
    retrieval_lexical_n: int = 50
    rrf_k: int = 60  # standard RRF dampener

    # --- Pipeline toggles ------------------------------------------------
    no_verify: bool = Field(False, description="--no-verify: skip auditor pass entirely")
    audit_low_conf_threshold: float = Field(
        0.75, description="Coder confidence at or below which the auditor is invoked"
    )
    audit_always_for_procedures: bool = True

    # --- Confidence tier thresholds (gold-tuned, see Plan.md §9.7) -------
    tier_high_threshold: float = 0.78
    tier_low_threshold: float = 0.45

    # --- Paths -----------------------------------------------------------
    # Stable local filename; contents are the CDC FY2027 release (the Makefile
    # renames icd10cm-codes-2027.txt -> ...2026.txt so this path stays constant).
    icd10_catalog: Path = Field(
        default_factory=lambda: REPO_ROOT / "data" / "catalogs" / "icd10cm_codes_2026.txt"
    )
    cpt_catalog: Path = Field(
        default_factory=lambda: REPO_ROOT / "data" / "catalogs" / "procedures_synthetic.csv"
    )
    index_dir: Path = Field(default_factory=lambda: REPO_ROOT / "data" / "index")
    cache_dir: Path = Field(default_factory=lambda: REPO_ROOT / ".cache" / "llm")

    # --- Observability ---------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    def model_for(self, agent: str) -> str:
        """Resolve the effective model ID for a pipeline agent.

        extraction/coder fall back to the shared ``llm_model``; the auditor uses
        ``verifier_model``. Centralised so logs, the config_hash, and the actual
        calls all agree on which model ran for each role.
        """
        if agent == "extraction":
            return self.extraction_model or self.llm_model
        if agent == "coder":
            return self.coder_model or self.llm_model
        if agent == "auditor":
            return self.verifier_model
        return self.llm_model

    def config_hash(self) -> str:
        """Stable hash over reproducibility-relevant settings."""
        relevant = {
            "llm_model": self.llm_model,
            "extraction_model": self.model_for("extraction"),
            "coder_model": self.model_for("coder"),
            "verifier_model": self.verifier_model,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "embedder": self.embedder,
            "retrieval_top_k": self.retrieval_top_k,
            "rrf_k": self.rrf_k,
            "no_verify": self.no_verify,
            "audit_low_conf_threshold": self.audit_low_conf_threshold,
            "tier_high_threshold": self.tier_high_threshold,
            "tier_low_threshold": self.tier_low_threshold,
            "pipeline_version": PIPELINE_VERSION,
            "prompt_version": PROMPT_VERSION,
        }
        blob = json.dumps(relevant, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


_settings: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    """Process-wide singleton; pass refresh=True after env mutation in tests."""
    global _settings
    if _settings is None or refresh:
        _settings = Settings()
    return _settings
