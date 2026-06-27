"""Per-run audit trace — a serializer over the pipeline's in-memory objects.

The brief asks for logging/tracing "suitable for audit": a reviewer should be
able to reconstruct *how each suggestion was reached*, not just see the final
codes. The final `CodingResult` shows the surviving codes; this trace adds the
decision trail behind them — what was extracted, which candidates the retriever
surfaced per fact, what the coder picked, and how the auditor voted.

It introduces no new computation: every field below is read off the
`PipelineResult` the pipeline already returns. `medcoder run` writes it to
`outputs/<doc_id>/trace.json` alongside the result (see cli.py).
"""

from __future__ import annotations

from typing import Any

from .pipeline import PipelineResult
from .schemas import CandidateCode, ExtractedFact


def _fact_summary(f: ExtractedFact) -> dict[str, Any]:
    return {
        "text": f.text,
        "normalized_term": f.normalized_term,
        "query_terms": f.query_terms,
        "assertion_status": f.assertion_status.value,
        "kind": f.kind,
        "section": f.section,
        "start_offset": f.start_offset,
        "end_offset": f.end_offset,
    }


def _candidate_summary(c: CandidateCode) -> dict[str, Any]:
    return {
        "code": c.code,
        "system": c.system.value,
        "description": c.description,
        "retrieval_score": round(c.retrieval_score, 6),
        "fused_rank": c.fused_rank,
    }


def build_trace(result: PipelineResult) -> dict[str, Any]:
    """Serialize a `PipelineResult` into a self-contained audit record.

    Returns a JSON-able dict with: top-level identity (`document_id`, `trace_id`,
    `config_hash`, `encounter_type`); a `stages` map with one key per pipeline
    stage (`extract`/`retrieve`/`code`/`audit`/`rules`) holding that stage's actual
    output; and `result` — the full final `CodingResult` — so the trace stands
    alone for a reviewer.
    """
    cr = result.coding_result

    # Retrieval whitelist per codable fact (keys of retrieval_by_fact index into
    # codable_facts — see pipeline._retrieve_for_facts).
    retrieval = []
    for i, candidates in sorted(result.retrieval_by_fact.items()):
        fact = result.codable_facts[i] if i < len(result.codable_facts) else None
        retrieval.append(
            {
                "fact": fact.normalized_term if fact else None,
                "kind": fact.kind if fact else None,
                "candidates": [_candidate_summary(c) for c in candidates],
            }
        )

    coder_assignments = [
        {
            "fact": a.fact.text,
            "code": a.candidate.code,
            "system": a.candidate.system.value,
            "description": a.candidate.description,
            "coder_confidence": a.choice.confidence,
            "rationale": a.choice.rationale,
        }
        for a in result.assignments
    ]

    audit_verdicts = [
        {
            "code": o.assignment.candidate.code,
            "agree": o.agree,  # None = audit skipped (high-confidence diagnosis)
            "note": o.note or None,
        }
        for o in result.outcomes
    ]

    return {
        "document_id": cr.document_id,
        "trace_id": cr.metadata.trace_id,
        "config_hash": cr.metadata.config_hash,
        "encounter_type": cr.metadata.encounter_type.value,
        "stages": {
            "extract": {"facts": [_fact_summary(f) for f in result.facts]},
            "retrieve": {"by_fact": retrieval},
            "code": {"assignments": coder_assignments},
            "audit": {"verdicts": audit_verdicts},
            "rules": {"warnings": [w.model_dump(mode="json") for w in cr.warnings]},
        },
        "result": cr.model_dump(mode="json"),
    }
