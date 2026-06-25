"""Auditor agent — independent model verifies each (evidence, code) pair.

Triage rules (Plan.md §8.3) keep this cheap:
  - ALWAYS audit procedures (high cost of error, smaller list).
  - ALWAYS audit if coder confidence ≤ audit_low_conf_threshold.
  - Otherwise skip — the lightweight whitelist + assertion checks are enough.

Batched: one auditor call per note covers every (evidence, code) pair flagged
for verification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .code_assign import CodedAssignment
from .config import get_settings
from .ingest import IngestedNote
from .llm import CallAggregator, call_structured
from .logging_setup import get_logger
from .prompts import AUDITOR_SYSTEM
from .schemas import (
    AuditorResponse,
    AuditorVerdict,
    CodeSystem,
)

log = get_logger(__name__)


@dataclass
class AuditOutcome:
    """One auditor verdict (or skipped placeholder) per coded assignment."""

    assignment: CodedAssignment
    agree: bool | None  # None = audit was skipped
    note: str = ""


def _needs_audit(assignment: CodedAssignment) -> bool:
    s = get_settings()
    if assignment.candidate.system == CodeSystem.CPT and s.audit_always_for_procedures:
        return True
    if assignment.choice.confidence <= s.audit_low_conf_threshold:
        return True
    return False


def _build_user_prompt(
    note: IngestedNote, pairs: list[tuple[int, CodedAssignment]]
) -> str:
    payload = {
        "encounter_type": note.encounter_type.value,
        "note_text": note.text,
        "pairs": [
            {
                "pair_index": idx,
                "evidence_text": a.fact.text,
                "evidence_section": a.fact.section,
                "evidence_start": a.fact.start_offset,
                "evidence_end": a.fact.end_offset,
                "assertion_status": a.fact.assertion_status.value,
                "code": a.candidate.code,
                "code_system": a.candidate.system.value,
                "code_description": a.candidate.description,
                "coder_rationale": a.choice.rationale,
                "coder_confidence": a.choice.confidence,
            }
            for idx, a in pairs
        ],
    }
    return (
        "Audit each (evidence, code) pair below. Return a verdict per `pair_index`.\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```"
    )


def audit_assignments(
    note: IngestedNote,
    assignments: list[CodedAssignment],
    *,
    aggregator: CallAggregator | None = None,
    mock_response: str | None = None,
) -> list[AuditOutcome]:
    """Return one AuditOutcome per assignment (skipped ones get agree=None)."""
    s = get_settings()
    if s.no_verify or not assignments:
        return [AuditOutcome(assignment=a, agree=None) for a in assignments]

    audit_indices = [i for i, a in enumerate(assignments) if _needs_audit(a)]
    pairs = [(i, assignments[i]) for i in audit_indices]
    outcomes: list[AuditOutcome] = [AuditOutcome(assignment=a, agree=None) for a in assignments]

    if not pairs:
        log.info("audit_all_skipped", extra={"n_assignments": len(assignments)})
        return outcomes

    resp: AuditorResponse = call_structured(
        agent="auditor",
        system_prompt=AUDITOR_SYSTEM,
        user_prompt=_build_user_prompt(note, pairs),
        schema=AuditorResponse,
        model=s.verifier_model,
        aggregator=aggregator,
        mock_response=mock_response,
    )

    by_idx: dict[int, AuditorVerdict] = {v.pair_index: v for v in resp.verdicts}
    for slot, assignment in enumerate(assignments):
        if slot not in audit_indices:
            continue
        v = by_idx.get(slot)
        if v is None:
            log.warning("audit_missing_verdict", extra={"slot": slot, "code": assignment.candidate.code})
            continue
        outcomes[slot] = AuditOutcome(
            assignment=assignment, agree=bool(v.agree), note=v.note or ""
        )
    log.info(
        "audit_done",
        extra={
            "audited": len(pairs),
            "agreed": sum(1 for o in outcomes if o.agree is True),
            "disagreed": sum(1 for o in outcomes if o.agree is False),
        },
    )
    return outcomes
