"""Extraction agent — assertion reconciliation + window-merged offsets.

The agent itself is mocked (no LLM), but the deterministic NegEx / family
backstop is real and exercised here.
"""

from __future__ import annotations

from medcoder.extract import coding_eligible, reconcile_assertion
from medcoder.schemas import AssertionStatus, ExtractedFact


def _fact(text: str, start: int, status: str = "present") -> ExtractedFact:
    return ExtractedFact(
        text=text,
        normalized_term=text.lower(),
        assertion_status=AssertionStatus(status),
        start_offset=start,
        end_offset=start + len(text),
        kind="diagnosis",
    )


def test_reconcile_catches_missed_negation():
    text = "Patient denies chest pain on review."
    f = _fact("chest pain", text.index("chest pain"), status="present")
    out = reconcile_assertion(f, text)
    assert out.assertion_status == AssertionStatus.ABSENT


def test_reconcile_catches_family_history():
    text = "Mother had myocardial infarction at 62."
    f = _fact("myocardial infarction", text.index("myocardial infarction"), status="present")
    out = reconcile_assertion(f, text)
    assert out.assertion_status == AssertionStatus.FAMILY


def test_reconcile_catches_historical_marker():
    text = "Past medical history: hypertension, well controlled."
    f = _fact("hypertension", text.index("hypertension"), status="present")
    out = reconcile_assertion(f, text)
    assert out.assertion_status == AssertionStatus.HISTORICAL


def test_reconcile_does_not_downgrade_clean_present():
    text = "Assessment: type 2 diabetes mellitus."
    f = _fact("type 2 diabetes mellitus", text.index("type 2"), status="present")
    out = reconcile_assertion(f, text)
    assert out.assertion_status == AssertionStatus.PRESENT


def test_reconcile_does_not_upgrade_negation_to_present():
    """Safety direction — we only OVERRULE present→other, never absent→present."""
    text = "Denies chest pain."
    f = _fact("chest pain", text.index("chest pain"), status="absent")
    out = reconcile_assertion(f, text)
    assert out.assertion_status == AssertionStatus.ABSENT


def test_coding_eligible_inpatient_vs_outpatient():
    f = ExtractedFact(
        text="pneumonia",
        normalized_term="pneumonia",
        assertion_status=AssertionStatus.POSSIBLE,
        start_offset=0,
        end_offset=9,
        kind="diagnosis",
    )
    # Outpatient: probable/suspected is NOT codeable (IV.H).
    assert coding_eligible(f, allow_possible_inpatient=False) is False
    # Inpatient: probable/suspected IS codeable.
    assert coding_eligible(f, allow_possible_inpatient=True) is True


def test_coding_eligible_filters_historical_and_family_under_both_encounters():
    """Historical findings and family-history are never coded as active diagnoses,
    regardless of encounter type. Coding either is the top false-positive source
    in clinical NLP."""
    for status in (AssertionStatus.HISTORICAL, AssertionStatus.FAMILY, AssertionStatus.ABSENT):
        f = ExtractedFact(
            text="myocardial infarction",
            normalized_term="myocardial infarction",
            assertion_status=status,
            start_offset=0,
            end_offset=21,
            kind="diagnosis",
        )
        assert coding_eligible(f, allow_possible_inpatient=False) is False, status
        assert coding_eligible(f, allow_possible_inpatient=True) is False, status


def test_coding_eligible_hypothetical_is_never_codeable():
    f = ExtractedFact(
        text="anaphylaxis",
        normalized_term="anaphylaxis",
        assertion_status=AssertionStatus.HYPOTHETICAL,
        start_offset=0,
        end_offset=11,
        kind="diagnosis",
    )
    assert coding_eligible(f, allow_possible_inpatient=False) is False
    assert coding_eligible(f, allow_possible_inpatient=True) is False


def test_reconcile_does_not_fire_on_post_term_negation():
    """NegEx scope is directional: only the 30-char window BEFORE the term is
    searched for negation triggers. A negative word that appears AFTER the term
    and refers to a different finding ('chest pain. No fever.') must NOT flip
    chest-pain to 'absent'. This guards against accidentally expanding the
    NegEx scope to the full context window, which would over-trigger.
    """
    text = "chest pain. No fever was noted."
    # 'No' applies to 'fever', not 'chest pain' — chest_pain remains 'present'
    f = _fact("chest pain", text.index("chest pain"), status="present")
    out = reconcile_assertion(f, text)
    assert out.assertion_status == AssertionStatus.PRESENT
