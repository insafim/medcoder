"""Coder agent — selects a code (or codes) for each fact from the retrieval whitelist.

The whitelist is a hard constraint: the agent's response is validated against
the candidates, and any out-of-whitelist code is dropped with a warning. This is
the mechanism that makes ICD-10 hallucinations *structurally impossible*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .config import get_settings
from .ingest import IngestedNote
from .llm import CallAggregator, call_structured
from .logging_setup import get_logger
from .prompts import CODER_SYSTEM
from .schemas import (
    CandidateCode,
    CoderCodeChoice,
    CoderResponse,
    CodeSystem,
    ExtractedFact,
)

log = get_logger(__name__)


@dataclass
class CoderInput:
    """Bundle a fact with its candidate whitelist; what the coder sees per fact."""

    fact_index: int
    fact: ExtractedFact
    candidates: list[CandidateCode]


@dataclass
class CodedAssignment:
    """One assigned code (after whitelist re-validation)."""

    fact: ExtractedFact
    candidate: CandidateCode
    choice: CoderCodeChoice


def _serialize_candidate(c: CandidateCode) -> dict[str, str]:
    return {
        "code": c.code,
        "system": c.system.value,
        "description": c.description,
    }


def _serialize_input(item: CoderInput) -> dict:
    return {
        "fact_index": item.fact_index,
        "text": item.fact.text,
        "normalized_term": item.fact.normalized_term,
        "assertion_status": item.fact.assertion_status.value,
        "section": item.fact.section,
        "kind": item.fact.kind,
        "candidates": [_serialize_candidate(c) for c in item.candidates],
    }


def _build_user_prompt(note: IngestedNote, items: list[CoderInput]) -> str:
    payload = {
        "encounter_type": note.encounter_type.value,
        "note_text": note.text,
        "facts": [_serialize_input(i) for i in items],
    }
    return (
        "Code each fact below using ONLY codes from its `candidates` list. "
        "Match each output to the `fact_index` it covers.\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```"
    )


def assign_codes(
    note: IngestedNote,
    items: list[CoderInput],
    *,
    aggregator: CallAggregator | None = None,
    mock_response: str | None = None,
) -> list[CodedAssignment]:
    """One batched call covering all facts in the note.

    Returns one CodedAssignment per accepted (fact, candidate, choice) triple;
    rejected (out-of-whitelist) choices are dropped and logged.
    """
    if not items:
        return []

    resp: CoderResponse = call_structured(
        agent="coder",
        system_prompt=CODER_SYSTEM,
        user_prompt=_build_user_prompt(note, items),
        schema=CoderResponse,
        model=get_settings().model_for("coder"),
        aggregator=aggregator,
        mock_response=mock_response,
    )

    by_index: dict[int, CoderInput] = {it.fact_index: it for it in items}
    out: list[CodedAssignment] = []
    for fr in resp.assignments:
        item = by_index.get(fr.fact_index)
        if item is None:
            log.warning("coder_unknown_fact_index", extra={"fact_index": fr.fact_index})
            continue
        candidate_by_code = {c.code: c for c in item.candidates}
        for choice in fr.choices:
            cand = candidate_by_code.get(choice.code)
            if cand is None:
                # Out-of-whitelist code — drop it (structural guarantee).
                log.warning(
                    "coder_offlist_code_dropped",
                    extra={
                        "fact_index": fr.fact_index,
                        "code": choice.code,
                        "valid_candidates": list(candidate_by_code.keys())[:5],
                    },
                )
                continue
            out.append(CodedAssignment(fact=item.fact, candidate=cand, choice=choice))
    log.info(
        "coding_done",
        extra={"n_facts_in": len(items), "n_assignments_out": len(out)},
    )
    return out


def split_by_system(
    assignments: list[CodedAssignment],
) -> tuple[list[CodedAssignment], list[CodedAssignment]]:
    """Split into (ICD-10 diagnoses, CPT procedures) for downstream assembly."""
    dx, px = [], []
    for a in assignments:
        if a.candidate.system == CodeSystem.ICD10:
            dx.append(a)
        elif a.candidate.system == CodeSystem.CPT:
            px.append(a)
    return dx, px
