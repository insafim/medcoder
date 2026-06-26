"""Extraction agent + assertion-status backstop.

The agent emits one ExtractedFact per clinical concept (verbatim span, normalized
term, assertion status). The deterministic NegEx/ConText backstop here is small
but catches the most common LLM polarity slip ("denies chest pain" → present).
"""

from __future__ import annotations

import re

from .config import get_settings
from .ingest import IngestedNote
from .llm import CallAggregator, call_structured
from .logging_setup import get_logger
from .prompts import EXTRACTION_SYSTEM
from .schemas import AssertionStatus, ExtractedFact, ExtractionResponse

log = get_logger(__name__)


# ---- deterministic backstop ---------------------------------------------

_NEGATION_PAT = re.compile(
    r"\b(?:no|denies|denied|denying|negative for|without|rules?\s+out|"
    r"r/o|free of|absence of|not (?:in|on)|"
    r"unremarkable for)\b",
    re.IGNORECASE,
)
_HEDGE_PAT = re.compile(
    r"\b(?:possible|possibly|probable|probably|suspected|likely|"
    r"questionable|consider(?:ing)?|differential includes|vs\.?|versus|"
    r"r/o|rule out|cannot exclude|cannot rule out)\b",
    re.IGNORECASE,
)
_FAMILY_PAT = re.compile(
    r"\b(?:family history|fhx|mother|father|sister|brother|"
    r"maternal|paternal|sibling|aunt|uncle|grandmother|grandfather|"
    r"parent(?:s)?)\b",
    re.IGNORECASE,
)
_HISTORICAL_PAT = re.compile(
    r"\b(?:history of|hx of|h/o|s/p|status[- ]post|previous|prior|past medical history)\b",
    re.IGNORECASE,
)


def _scan_window(text: str, start: int, end: int, window: int = 30) -> str:
    """Return the small context window around a span — what NegEx/ConText looks at."""
    a = max(0, start - window)
    b = min(len(text), end + window)
    return text[a:b]


def reconcile_assertion(fact: ExtractedFact, full_text: str) -> ExtractedFact:
    """Use small lexical scanners to overrule a clearly wrong LLM assertion.

    Only OVERRULES when the lexical signal is unambiguous and disagrees with the
    LLM. We never *upgrade* "absent" → "present" because the LLM's structural
    reading is more reliable for the positive case; we only catch missed
    negations / hedges / family / history (the safety direction).
    """
    if fact.start_offset >= len(full_text):
        return fact
    context = _scan_window(full_text, fact.start_offset, fact.end_offset)
    # Negation has to occur **before** the term within the window (NegEx scope)
    pre_context = full_text[max(0, fact.start_offset - 30) : fact.start_offset]

    if fact.assertion_status == AssertionStatus.PRESENT:
        if _NEGATION_PAT.search(pre_context):
            log.info(
                "assertion_reconciled",
                extra={"text": fact.text[:60], "from": "present", "to": "absent"},
            )
            return fact.model_copy(update={"assertion_status": AssertionStatus.ABSENT})
        if _FAMILY_PAT.search(pre_context):
            return fact.model_copy(update={"assertion_status": AssertionStatus.FAMILY})
        if _HISTORICAL_PAT.search(pre_context):
            return fact.model_copy(update={"assertion_status": AssertionStatus.HISTORICAL})
        if _HEDGE_PAT.search(pre_context) or _HEDGE_PAT.search(context):
            return fact.model_copy(update={"assertion_status": AssertionStatus.POSSIBLE})
    return fact


# ---- merge ---------------------------------------------------------------


def _merge_facts(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    """Dedupe across windows by (normalized_term, kind, assertion_status).

    When the same fact recurs, keep the earliest mention (deterministic order).
    """
    seen: dict[tuple[str, str, str], ExtractedFact] = {}
    for f in facts:
        key = (f.normalized_term.lower(), f.kind, f.assertion_status.value)
        if key not in seen or f.start_offset < seen[key].start_offset:
            seen[key] = f
    return sorted(seen.values(), key=lambda f: f.start_offset)


# ---- extraction entry point ---------------------------------------------


def _build_user_prompt(note_text: str, window_offset: int = 0) -> str:
    # Tell the model the offset base so it returns global offsets.
    return (
        f"Note text follows (character offsets are 0-based into this exact text; "
        f"this window starts at global offset {window_offset}). "
        f"Return offsets relative to THIS window — the pipeline will translate.\n\n"
        f"=== NOTE BEGIN ===\n{note_text}\n=== NOTE END ==="
    )


def extract_facts(
    note: IngestedNote,
    *,
    aggregator: CallAggregator | None = None,
    mock_response: str | None = None,
) -> list[ExtractedFact]:
    """Run the extraction agent over every window and merge results."""
    model = get_settings().model_for("extraction")
    all_facts: list[ExtractedFact] = []
    for window in note.windows:
        resp = call_structured(
            agent="extraction",
            system_prompt=EXTRACTION_SYSTEM,
            user_prompt=_build_user_prompt(window.text, window.start),
            schema=ExtractionResponse,
            model=model,
            aggregator=aggregator,
            mock_response=mock_response,
        )
        for f in resp.facts:
            # Translate window-local offsets to global note offsets.
            shift = window.start
            translated = f.model_copy(
                update={
                    "start_offset": f.start_offset + shift,
                    "end_offset": f.end_offset + shift,
                }
            )
            # Snap the text to whatever is actually at that offset (LLM may drift).
            if (
                0 <= translated.start_offset < len(note.text)
                and 0 <= translated.end_offset <= len(note.text)
                and translated.end_offset > translated.start_offset
            ):
                actual = note.text[translated.start_offset : translated.end_offset]
                if actual != translated.text:
                    # Try to relocate by exact match within the window.
                    found = note.text.find(f.text, window.start, window.end)
                    if found != -1:
                        translated = translated.model_copy(
                            update={
                                "start_offset": found,
                                "end_offset": found + len(f.text),
                                "text": f.text,
                            }
                        )
                    else:
                        translated = translated.model_copy(update={"text": actual})
            all_facts.append(reconcile_assertion(translated, note.text))

    merged = _merge_facts(all_facts)
    log.info(
        "extraction_done",
        extra={"n_raw": len(all_facts), "n_merged": len(merged)},
    )
    return merged


def coding_eligible(fact: ExtractedFact, *, allow_possible_inpatient: bool = False) -> bool:
    """Filter applied between extraction and retrieval.

    Per ICD-10-CM Guideline IV.H, outpatient encounters NEVER code "possible /
    suspected / probable" diagnoses; inpatient encounters may. The caller passes
    the appropriate flag based on encounter type.
    """
    if fact.assertion_status == AssertionStatus.PRESENT:
        return True
    if fact.assertion_status == AssertionStatus.POSSIBLE and allow_possible_inpatient:
        return True
    return False
