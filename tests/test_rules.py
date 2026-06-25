"""Rule engine — warnings for unspecified, missing 7th char, Excludes1, no-dx."""

from __future__ import annotations

from medcoder.code_assign import CodedAssignment
from medcoder.rules import RuleContext, evaluate
from medcoder.schemas import (
    AssertionStatus,
    CandidateCode,
    CoderCodeChoice,
    CodeSystem,
    ExtractedFact,
    WarningType,
)


def _assignment(code: str, system: CodeSystem, description: str, confidence: float = 0.8):
    fact = ExtractedFact(
        text="x", normalized_term="x", assertion_status=AssertionStatus.PRESENT,
        start_offset=0, end_offset=1, kind="diagnosis",
    )
    cand = CandidateCode(
        code=code, system=system, description=description, retrieval_score=0.5,
        dense_rank=1, lexical_rank=1,
    )
    choice = CoderCodeChoice(code=code, confidence=confidence, rationale="r")
    return CodedAssignment(fact=fact, candidate=cand, choice=choice)


def test_excludes1_e10_vs_e11_conflict():
    ctx = RuleContext(
        diagnoses=[
            _assignment("E10.9", CodeSystem.ICD10, "Type 1 diabetes mellitus without complications"),
            _assignment("E11.9", CodeSystem.ICD10, "Type 2 diabetes mellitus without complications"),
        ],
        procedures=[],
    )
    warnings = evaluate(ctx)
    types = [w.type for w in warnings]
    assert WarningType.CONFLICT in types
    conflict = next(w for w in warnings if w.type == WarningType.CONFLICT)
    assert "E10.9" in conflict.refs and "E11.9" in conflict.refs


def test_unspecified_code_emits_missing_info_warning():
    # E11.9 description does NOT contain 'unspecified' → no specificity warning
    no_warn_ctx = RuleContext(
        diagnoses=[
            _assignment(
                "E11.9",
                CodeSystem.ICD10,
                "Type 2 diabetes mellitus without complications",
                confidence=0.6,
            )
        ],
        procedures=[],
    )
    warnings_no = evaluate(no_warn_ctx)
    assert all(w.type != WarningType.MISSING_INFORMATION for w in warnings_no), (
        "E11.9 description doesn't include 'unspecified' — should not trigger the warning"
    )

    # J18.9 IS 'unspecified' and confidence is below 0.9 → warning expected
    warn_ctx = RuleContext(
        diagnoses=[
            _assignment(
                "J18.9",
                CodeSystem.ICD10,
                "Pneumonia, unspecified organism",
                confidence=0.6,
            )
        ],
        procedures=[],
    )
    warnings_yes = evaluate(warn_ctx)
    assert any(w.type == WarningType.MISSING_INFORMATION for w in warnings_yes)


def test_seventh_char_missing_warning():
    # S72.001 is a hip fracture code that needs a 7th char (A/D/S etc.)
    ctx = RuleContext(
        diagnoses=[_assignment("S72.001", CodeSystem.ICD10, "Fracture of unspecified part of neck of right femur")],
        procedures=[],
    )
    warnings = evaluate(ctx)
    # Behaviour assertion (type+severity), not message-text substring (fragile)
    assert any(
        w.type == WarningType.MISSING_INFORMATION and "S72.001" in w.refs
        for w in warnings
    )


def test_procedure_without_diagnosis_warns():
    ctx = RuleContext(
        diagnoses=[],
        procedures=[_assignment("9C0010", CodeSystem.CPT, "[SYNTHETIC] Electrocardiogram")],
    )
    warnings = evaluate(ctx)
    assert any(
        w.type == WarningType.MISSING_INFORMATION and "9C0010" in w.refs
        for w in warnings
    )


def test_invalid_icd10_format_blocks():
    ctx = RuleContext(
        diagnoses=[_assignment("NOT-A-CODE", CodeSystem.ICD10, "garbage")],
        procedures=[],
    )
    warnings = evaluate(ctx)
    assert any(w.severity.value == "block" for w in warnings)
