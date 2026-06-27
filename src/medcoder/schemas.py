"""Pydantic data contracts for the medical-coding pipeline.

Every stage exchanges these models; the final reviewer payload is
`CodingResult`. Field names track Plan.md §10 directly so the schema is
diff-able against the design.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssertionStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    POSSIBLE = "possible"
    HYPOTHETICAL = "hypothetical"
    FAMILY = "family"
    HISTORICAL = "historical"


class CodeSystem(str, Enum):
    ICD10 = "ICD-10-CM"
    CPT = "CPT"


class ConfidenceTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WarningType(str, Enum):
    MISSING_INFORMATION = "missing_information"
    AMBIGUITY = "ambiguity"
    CONFLICT = "conflict"


class WarningSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class ReviewerDecision(str, Enum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"


class EncounterType(str, Enum):
    """Care setting — gates the ICD-10-CM Guideline IV.H "uncertain diagnosis" rule
    (outpatient: don't code probable/suspected; inpatient: code as if present)."""

    INPATIENT = "inpatient"
    OUTPATIENT = "outpatient"
    UNKNOWN = "unknown"


class ExtractedFact(BaseModel):
    """One clinical concept lifted from the note, with verbatim evidence."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="Verbatim span from the note")
    normalized_term: str = Field(..., description="Canonical clinical phrase used for retrieval")
    query_terms: list[str] = Field(
        default_factory=list,
        description="Synonyms / abbreviation↔expansion used for retrieval query expansion",
    )
    assertion_status: AssertionStatus
    start_offset: int = Field(..., ge=0, description="Global char offset into the original note")
    end_offset: int = Field(..., ge=0)
    section: str | None = Field(None, description="SOAP section if detected")
    kind: Literal["diagnosis", "procedure", "symptom"] = "diagnosis"


class CandidateCode(BaseModel):
    """A code returned by the retriever, before the coder agent picks one."""

    model_config = ConfigDict(extra="forbid")

    code: str
    system: CodeSystem
    description: str
    retrieval_score: float = Field(..., description="Fused RRF score (higher = better)")
    dense_rank: int | None = None
    lexical_rank: int | None = None
    fused_rank: int | None = Field(
        None, description="1-based position in the fused/merged candidate list"
    )


class Warning(BaseModel):
    """A typed warning surfaced to the human reviewer."""

    model_config = ConfigDict(extra="forbid")

    type: WarningType
    severity: WarningSeverity = WarningSeverity.WARN
    message: str
    refs: list[str] = Field(default_factory=list, description="Code(s) the warning is about")


class CodeSuggestion(BaseModel):
    """One suggested code plus everything a reviewer needs to accept/override."""

    model_config = ConfigDict(extra="forbid")

    code: str
    system: CodeSystem
    description: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_tier: ConfidenceTier
    rationale: str
    evidence: list[ExtractedFact] = Field(default_factory=list)
    status: Literal["primary", "secondary", "uncertain"] = "primary"
    # Reviewer override surface (mutable lifecycle, see §11)
    reviewer_decision: ReviewerDecision = ReviewerDecision.SUGGESTED
    reviewer_code: str | None = None
    reviewer_note: str | None = None
    # Provenance from the agents
    audit_agree: bool | None = Field(
        None, description="Whether the auditor agreed; None means audit was skipped"
    )
    audit_note: str | None = None


class RunMetrics(BaseModel):
    """Per-run observability — latency, tokens, cost, retries."""

    model_config = ConfigDict(extra="forbid")

    stage_latency_ms: dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    tokens: dict[str, int] = Field(default_factory=dict)  # prompt/completion/total per agent
    est_cost_usd: float = 0.0
    retries: int = 0
    n_candidates: int = 0
    n_warnings: int = 0
    n_facts: int = 0
    n_facts_coded: int = 0


class RunMetadata(BaseModel):
    """Audit envelope written next to every CodingResult."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    model_ids: dict[str, str] = Field(
        default_factory=dict, description="agent -> model snapshot string"
    )
    pipeline_version: str
    temperature: float = 0.0
    config_hash: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    encounter_type: EncounterType = EncounterType.UNKNOWN
    metrics: RunMetrics = Field(default_factory=RunMetrics)


class CodingResult(BaseModel):
    """Top-level reviewer-ready payload."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    diagnoses: list[CodeSuggestion] = Field(default_factory=list)
    procedures: list[CodeSuggestion] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    metadata: RunMetadata


# ---- LLM I/O schemas (what each agent emits, before assembly) --------------


class ExtractionResponse(BaseModel):
    """What the extraction agent returns (one call per note/window-batch)."""

    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact]
    encounter_type: EncounterType | None = Field(
        None,
        description="Note-level encounter classification; None/unknown → heuristic fallback",
    )


class CoderCodeChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="MUST be one of the candidates supplied to the coder")
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str


class CoderFactResponse(BaseModel):
    """Coder's answer for one extracted fact."""

    model_config = ConfigDict(extra="forbid")

    fact_index: int
    choices: list[CoderCodeChoice] = Field(
        default_factory=list,
        description="Empty list means no candidate was good enough (handle as low-conf warning)",
    )


class CoderResponse(BaseModel):
    """Coder agent return — covers all facts in one batched call."""

    model_config = ConfigDict(extra="forbid")

    assignments: list[CoderFactResponse]


class AuditorVerdict(BaseModel):
    """One auditor judgement for one (evidence, code) pair."""

    model_config = ConfigDict(extra="forbid")

    pair_index: int
    agree: bool
    note: str = ""


class AuditorResponse(BaseModel):
    """Auditor agent return — one verdict per pair the caller supplied."""

    model_config = ConfigDict(extra="forbid")

    verdicts: list[AuditorVerdict]
