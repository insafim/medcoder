"""Ingestion stage — deterministic preprocessing of raw notes.

Pipeline: normalise → detect encounter type → segment SOAP → window long
notes with overlap → preserve **global** char offsets.

Global offsets matter because every evidence span in the final payload must point
back to a coordinate in the *original* note, not into a window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import EncounterType

# ---- normalisation -------------------------------------------------------

_WS_RUN = re.compile(r"[ \t]+")
_NL_RUN = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    """Lossless-ish cleanup: collapse runs of spaces/newlines, normalise newlines.

    Length-preserving where possible; offsets in the returned text are stable
    relative to itself but NOT identical to the raw input. The pipeline operates
    on the normalised text and reports offsets relative to it. The raw text is
    retained by the caller for reproducibility.
    """
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = _WS_RUN.sub(" ", t)
    t = _NL_RUN.sub("\n\n", t)
    return t.strip()


# ---- encounter type ------------------------------------------------------

_INPATIENT_HINTS = (
    "admission",
    "admitted",
    "admit to",
    "inpatient",
    "icu",
    "intensive care",
    "ward",
    "hospital course",
    "discharge summary",
    "h&p",
    "history and physical",
)
_OUTPATIENT_HINTS = (
    "office visit",
    "outpatient",
    "clinic note",
    "follow-up",
    "follow up",
    "primary care",
    "telehealth",
    "telemedicine",
    "telephone visit",
    "ambulatory",
    "emergency department",  # ED is technically outpatient for coding
    "ed visit",
)


def detect_encounter_type(text: str) -> EncounterType:
    """Heuristic — explicit > inpatient > outpatient > unknown.

    The encounter type is consequential: outpatient bars coding of
    probable / suspected diagnoses (ICD-10-CM Guideline IV.H), while inpatient
    allows it. Used downstream in rules.py and confidence weighting.
    """
    lower = text.lower()
    inpatient_score = sum(h in lower for h in _INPATIENT_HINTS)
    outpatient_score = sum(h in lower for h in _OUTPATIENT_HINTS)
    if inpatient_score == 0 and outpatient_score == 0:
        return EncounterType.UNKNOWN
    if inpatient_score > outpatient_score:
        return EncounterType.INPATIENT
    if outpatient_score > inpatient_score:
        return EncounterType.OUTPATIENT
    # tie → default to outpatient (more conservative for uncertain dx)
    return EncounterType.OUTPATIENT


# ---- SOAP segmentation ---------------------------------------------------

_SECTION_HEADER = re.compile(
    r"^(?P<name>"
    r"subjective|objective|assessment|plan|"
    r"chief complaint|history of present illness|hpi|"
    r"past medical history|pmh|medications|allergies|"
    r"review of systems|ros|physical exam|examination|"
    r"impression|diagnosis|diagnoses|procedure|procedures|"
    r"hospital course|discharge diagnosis|labs|imaging|results"
    r")\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass
class Section:
    name: str
    text: str
    start: int  # char offset in the normalised document
    end: int


def segment_soap(text: str) -> list[Section]:
    """Split a note into labelled sections by SOAP-style headers."""
    matches = list(_SECTION_HEADER.finditer(text))
    if not matches:
        return [Section(name="body", text=text, start=0, end=len(text))]
    sections: list[Section] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append(
                Section(
                    name=m.group("name").lower(),
                    text=body,
                    start=start,
                    end=end,
                )
            )
    return sections


# ---- windowing -----------------------------------------------------------


@dataclass
class Window:
    text: str
    start: int  # global offset in the normalised note
    end: int
    index: int  # 0-based window number


def window_text(text: str, max_chars: int = 6000, overlap: int = 400) -> list[Window]:
    """Split a long note into overlapping windows.

    `max_chars` is a coarse proxy for token budget (≈ 1500 tokens). Overlap
    avoids cutting an evidence sentence in half. **Returned offsets are global**
    so downstream stages can stitch evidence back to the original.
    """
    if len(text) <= max_chars:
        return [Window(text=text, start=0, end=len(text), index=0)]
    windows: list[Window] = []
    i = 0
    idx = 0
    while i < len(text):
        end = min(i + max_chars, len(text))
        # Try to break on a sentence/paragraph boundary near `end`.
        if end < len(text):
            slice_ = text[i:end]
            for sep in ("\n\n", "\n", ". "):
                k = slice_.rfind(sep)
                if k != -1 and k > max_chars // 2:
                    end = i + k + len(sep)
                    break
        windows.append(Window(text=text[i:end], start=i, end=end, index=idx))
        if end >= len(text):
            break
        i = end - overlap
        idx += 1
    return windows


# ---- top-level -----------------------------------------------------------


@dataclass
class IngestedNote:
    raw_text: str
    text: str  # normalised
    encounter_type: EncounterType
    sections: list[Section]
    windows: list[Window]


def ingest(raw_text: str) -> IngestedNote:
    """Public stage entry: normalise → detect encounter type → SOAP-segment → window.

    Returned ``IngestedNote`` has both ``raw_text`` (the caller's input) and
    ``text`` (the normalised form); all downstream offsets are relative to
    ``text``.
    """
    text = normalize(raw_text)
    return IngestedNote(
        raw_text=raw_text,
        text=text,
        encounter_type=detect_encounter_type(text),
        sections=segment_soap(text),
        windows=window_text(text),
    )
