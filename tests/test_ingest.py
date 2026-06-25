"""Ingestion — normalisation, encounter detection, SOAP segmentation, windowing."""

from __future__ import annotations

from medcoder.ingest import (
    detect_encounter_type,
    ingest,
    normalize,
    segment_soap,
    window_text,
)
from medcoder.schemas import EncounterType


def test_normalize_collapses_runs():
    assert normalize("a   b\r\n\r\n\r\n\r\nc") == "a b\n\nc"


def test_detect_encounter_type_outpatient():
    text = "Office visit follow-up. Outpatient clinic note."
    assert detect_encounter_type(text) == EncounterType.OUTPATIENT


def test_detect_encounter_type_inpatient():
    text = "Hospital course: patient was admitted to the ICU."
    assert detect_encounter_type(text) == EncounterType.INPATIENT


def test_detect_encounter_type_unknown():
    assert detect_encounter_type("nothing obvious here") == EncounterType.UNKNOWN


def test_detect_encounter_type_tie_defaults_to_outpatient():
    """When inpatient and outpatient hints match, the conservative default is
    outpatient — under outpatient rules, 'probable/suspected' diagnoses are NOT
    codeable (ICD-10-CM IV.H), which is the safer error direction."""
    # One inpatient hint ('admitted'), one outpatient hint ('follow-up')
    text = "Patient was admitted yesterday. This is a follow-up note."
    assert detect_encounter_type(text) == EncounterType.OUTPATIENT


def test_segment_soap_picks_up_headers():
    text = (
        "Subjective:\nPatient reports cough.\n\n"
        "Objective:\nTemp 38.0.\n\n"
        "Assessment:\nPneumonia.\n\n"
        "Plan:\nAntibiotics."
    )
    sections = segment_soap(text)
    names = [s.name for s in sections]
    assert names == ["subjective", "objective", "assessment", "plan"]
    assert "Pneumonia" in [s.text for s in sections if s.name == "assessment"][0]


def test_window_text_preserves_global_offsets():
    # 12000 chars in one paragraph forces windowing
    long = ("a " * 6000).strip()
    windows = window_text(long, max_chars=4000, overlap=200)
    assert len(windows) >= 3
    # Stitching the windows back together (with overlap) recovers the whole text.
    rebuilt = ""
    cursor = 0
    for w in windows:
        # New content starts at w.start; if that overlaps with what we already wrote,
        # the offset stays consistent — we just trust w.start as the global anchor.
        if w.start > cursor:
            # gap: shouldn't happen
            assert False, "gap between windows"
        new_start = cursor - w.start
        rebuilt += w.text[new_start:]
        cursor = w.end
    assert rebuilt == long


def test_ingest_end_to_end_outpatient_note():
    text = (
        "Outpatient follow-up.\n"
        "Subjective:\nPatient reports fatigue.\n"
        "Assessment:\nType 2 diabetes mellitus.\n"
    )
    note = ingest(text)
    assert note.encounter_type == EncounterType.OUTPATIENT
    assert len(note.windows) == 1  # short note
    assert any(s.name == "assessment" for s in note.sections)
