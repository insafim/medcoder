"""End-to-end orchestration: note → CodingResult.

Stages (per Plan.md §6):
    ingest → extract → retrieve → code → audit → rules → assemble

Each stage:
  - emits a structured log event with elapsed_ms keyed by trace_id;
  - participates in per-fact graceful degradation (a failure becomes a warning,
    not a crashed run);
  - flows into the same RunMetrics object so the final payload carries a
    complete observability fingerprint.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .code_assign import CoderInput, assign_codes, split_by_system
from .confidence import blend, make_inputs, tier_for
from .config import PIPELINE_VERSION, get_settings
from .extract import coding_eligible, extract_facts
from .ingest import IngestedNote, ingest
from .llm import CallAggregator
from .logging_setup import get_logger, new_trace_id, timed, trace_context
from .retrieval.hybrid import get_retriever
from .rules import RuleContext
from .rules import evaluate as evaluate_rules
from .schemas import (
    CandidateCode,
    CodeSuggestion,
    CodeSystem,
    CodingResult,
    EncounterType,
    ExtractedFact,
    ReviewerDecision,
    RunMetadata,
    RunMetrics,
    Warning,
    WarningSeverity,
    WarningType,
)
from .verify import AuditOutcome, audit_assignments

log = get_logger(__name__)


# ---- mock plumbing (tests only) -----------------------------------------


@dataclass
class MockResponses:
    """Optional canned LLM responses for offline test runs.

    Real usage leaves these as None and uses live LLM calls. Tests inject the
    JSON strings each agent should emit.
    """

    extraction: str | None = None
    coder: str | None = None
    auditor: str | None = None


# ---- pipeline -----------------------------------------------------------


@dataclass
class PipelineResult:
    coding_result: CodingResult
    # Convenience: indexed access to retrieval lists if a downstream eval wants them
    retrieval_by_fact: dict[int, list[CandidateCode]] = field(default_factory=dict)


def _kind_to_system(kind: str) -> CodeSystem:
    return CodeSystem.CPT if kind == "procedure" else CodeSystem.ICD10


def _retrieve_for_facts(
    facts: list[ExtractedFact],
) -> dict[int, list[CandidateCode]]:
    top_k = get_settings().retrieval_top_k
    out: dict[int, list[CandidateCode]] = {}
    for i, f in enumerate(facts):
        system = _kind_to_system(f.kind)
        retriever = get_retriever(system)
        # Query expansion: retrieve on the normalized term AND any LLM-supplied
        # synonyms, then merge candidates keeping the best score per code. Widens
        # recall without relaxing the whitelist (§9.3).
        merged: dict[str, CandidateCode] = {}
        for q in [f.normalized_term, *f.query_terms]:
            if not q or not q.strip():
                continue
            for c in retriever.search(q):
                prev = merged.get(c.code)
                if prev is None or c.retrieval_score > prev.retrieval_score:
                    merged[c.code] = c
        ranked = sorted(merged.values(), key=lambda c: -c.retrieval_score)[:top_k]
        for pos, c in enumerate(ranked, start=1):
            # in-place mutation is intentional (Pydantic model, not frozen):
            c.fused_rank = pos  # final post-merge rank feeds confidence (§9.7)
        out[i] = ranked
    return out


def run(
    note_text: str,
    *,
    document_id: str = "note",
    trace_id: str | None = None,
    mocks: MockResponses | None = None,
) -> PipelineResult:
    """Run the full pipeline on a single note."""
    settings = get_settings()
    mocks = mocks or MockResponses()
    agg = CallAggregator()
    metrics = RunMetrics()

    with trace_context(trace_id or new_trace_id()) as tid:
        start = time.perf_counter()

        # ---- 1) Ingest ------------------------------------------------
        with timed("ingest", metrics.stage_latency_ms):
            note: IngestedNote = ingest(note_text)
        log.info(
            "ingested",
            extra={
                "encounter_type": note.encounter_type.value,
                "n_sections": len(note.sections),
                "n_windows": len(note.windows),
                "n_chars": len(note.text),
            },
        )

        warnings: list[Warning] = []

        # ---- 2) Extract ----------------------------------------------
        llm_encounter: EncounterType | None = None
        facts: list[ExtractedFact] = []
        try:
            with timed("extract", metrics.stage_latency_ms):
                extraction = extract_facts(note, aggregator=agg, mock_response=mocks.extraction)
            facts = extraction.facts
            llm_encounter = extraction.encounter_type
        except Exception as e:  # noqa: BLE001  pipeline-level boundary
            log.exception("extract_failed", extra={"error": str(e)})
            warnings.append(
                Warning(
                    type=WarningType.MISSING_INFORMATION,
                    severity=WarningSeverity.BLOCK,
                    message=f"Extraction failed; no codes produced. Reason: {e}",
                )
            )
            facts = []
        metrics.n_facts = len(facts)

        # Encounter type: prefer the extraction LLM's whole-note classification;
        # fall back to the deterministic ingest heuristic when it is unsure (§9.1).
        encounter_type = (
            llm_encounter
            if llm_encounter not in (None, EncounterType.UNKNOWN)
            else note.encounter_type
        )
        allow_inpatient = encounter_type == EncounterType.INPATIENT
        codable = [f for f in facts if coding_eligible(f, allow_possible_inpatient=allow_inpatient)]
        skipped = [f for f in facts if f not in codable]
        for f in skipped:
            warnings.append(
                Warning(
                    type=WarningType.AMBIGUITY,
                    severity=WarningSeverity.INFO,
                    message=(
                        f"Fact {f.normalized_term!r} dropped from coding (assertion="
                        f"{f.assertion_status.value}); retained as context only."
                    ),
                    refs=[],
                )
            )

        # ---- 3) Retrieve ---------------------------------------------
        retrieval: dict[int, list[CandidateCode]] = {}
        try:
            with timed("retrieve", metrics.stage_latency_ms):
                retrieval = _retrieve_for_facts(codable)
        except Exception as e:  # noqa: BLE001
            log.exception("retrieve_failed", extra={"error": str(e)})
            warnings.append(
                Warning(
                    type=WarningType.MISSING_INFORMATION,
                    severity=WarningSeverity.BLOCK,
                    message=f"Retrieval failed: {e}",
                )
            )
        metrics.n_candidates = sum(len(v) for v in retrieval.values())

        coder_inputs = [
            CoderInput(fact_index=i, fact=codable[i], candidates=retrieval.get(i, []))
            for i in range(len(codable))
            if retrieval.get(i)
        ]

        # ---- 4) Code -------------------------------------------------
        assignments = []
        try:
            with timed("code", metrics.stage_latency_ms):
                assignments = assign_codes(
                    note, coder_inputs, aggregator=agg, mock_response=mocks.coder
                )
        except Exception as e:  # noqa: BLE001
            log.exception("code_failed", extra={"error": str(e)})
            warnings.append(
                Warning(
                    type=WarningType.MISSING_INFORMATION,
                    severity=WarningSeverity.BLOCK,
                    message=f"Coding agent failed: {e}",
                )
            )
        metrics.n_facts_coded = len({a.fact.start_offset for a in assignments})

        # ---- 5) Audit ------------------------------------------------
        outcomes: list[AuditOutcome] = []
        try:
            with timed("audit", metrics.stage_latency_ms):
                outcomes = audit_assignments(
                    note, assignments, aggregator=agg, mock_response=mocks.auditor
                )
        except Exception as e:  # noqa: BLE001
            log.exception("audit_failed", extra={"error": str(e)})
            warnings.append(
                Warning(
                    type=WarningType.AMBIGUITY,
                    severity=WarningSeverity.INFO,
                    message=(
                        f"Auditor pass failed — codes shown without independent verification: {e}"
                    ),
                )
            )
            outcomes = [AuditOutcome(assignment=a, agree=None) for a in assignments]

        # ---- 6) Rules ------------------------------------------------
        dx_assignments, px_assignments = split_by_system(assignments)
        with timed("rules", metrics.stage_latency_ms):
            rule_warnings = evaluate_rules(
                RuleContext(diagnoses=dx_assignments, procedures=px_assignments)
            )
        warnings.extend(rule_warnings)

        # ---- 7) Assemble suggestions --------------------------------
        with timed("assemble", metrics.stage_latency_ms):
            diagnoses = _to_suggestions(outcomes, system=CodeSystem.ICD10, warnings=warnings)
            procedures = _to_suggestions(outcomes, system=CodeSystem.CPT, warnings=warnings)
            metrics.n_warnings = len(warnings)

        # ---- finalise metrics --------------------------------------
        metrics.total_latency_ms = (time.perf_counter() - start) * 1000.0
        metrics.tokens = agg.token_totals()
        metrics.est_cost_usd = round(agg.cost_usd, 6)
        metrics.retries = agg.retries

        metadata = RunMetadata(
            # tid is guaranteed non-None inside the `with trace_context(...)` block.
            trace_id=tid,
            model_ids={
                "extraction": settings.model_for("extraction"),
                "coder": settings.model_for("coder"),
                "auditor": settings.model_for("auditor") if not settings.no_verify else "",
            },
            pipeline_version=PIPELINE_VERSION,
            temperature=settings.temperature,
            config_hash=settings.config_hash(),
            encounter_type=encounter_type,
            metrics=metrics,
        )
        result = CodingResult(
            document_id=document_id,
            diagnoses=diagnoses,
            procedures=procedures,
            warnings=warnings,
            metadata=metadata,
        )
        log.info(
            "pipeline_done",
            extra={
                "n_dx": len(diagnoses),
                "n_px": len(procedures),
                "n_warnings": len(warnings),
                "latency_ms": round(metrics.total_latency_ms, 2),
                "cost_usd": round(metrics.est_cost_usd, 6),
            },
        )
        return PipelineResult(coding_result=result, retrieval_by_fact=retrieval)


# ---- helpers --------------------------------------------------------------


def _to_suggestions(
    outcomes: list[AuditOutcome],
    *,
    system: CodeSystem,
    warnings: list[Warning],
) -> list[CodeSuggestion]:
    out: list[CodeSuggestion] = []
    for o in outcomes:
        a = o.assignment
        if a.candidate.system != system:
            continue
        inputs = make_inputs(
            candidate=a.candidate,
            coder_confidence=a.choice.confidence,
            audit_agree=o.agree,
        )
        score = blend(inputs)
        tier = tier_for(score)
        if o.agree is False:
            warnings.append(
                Warning(
                    type=WarningType.AMBIGUITY,
                    severity=WarningSeverity.WARN,
                    message=(
                        f"Auditor disagreed with code {a.candidate.code}: {o.note}"
                        if o.note
                        else f"Auditor disagreed with code {a.candidate.code}."
                    ),
                    refs=[a.candidate.code],
                )
            )
        suggestion = CodeSuggestion(
            code=a.candidate.code,
            system=a.candidate.system,
            description=a.candidate.description,
            confidence=round(score, 4),
            confidence_tier=tier,
            rationale=a.choice.rationale,
            evidence=[a.fact],
            status="primary",
            reviewer_decision=ReviewerDecision.SUGGESTED,
            audit_agree=o.agree,
            audit_note=o.note or None,
        )
        out.append(suggestion)
    # stable order: highest confidence first
    out.sort(key=lambda s: -s.confidence)
    return out
