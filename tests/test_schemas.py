"""Schemas — make sure the public payload is well-formed and validates correctly."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from medcoder.schemas import (
    AssertionStatus,
    CodeSuggestion,
    CodeSystem,
    CodingResult,
    ConfidenceTier,
    ExtractedFact,
    ReviewerDecision,
    RunMetadata,
    Warning,
    WarningSeverity,
    WarningType,
)


def _sample_fact() -> ExtractedFact:
    return ExtractedFact(
        text="type 2 diabetes mellitus",
        normalized_term="type 2 diabetes mellitus",
        assertion_status=AssertionStatus.PRESENT,
        start_offset=10,
        end_offset=34,
        section="assessment",
        kind="diagnosis",
    )


def _sample_suggestion(code: str = "E11.9") -> CodeSuggestion:
    return CodeSuggestion(
        code=code,
        system=CodeSystem.ICD10,
        description="Type 2 diabetes mellitus without complications",
        confidence=0.83,
        confidence_tier=ConfidenceTier.HIGH,
        rationale="Note states 'type 2 diabetes mellitus' in the assessment.",
        evidence=[_sample_fact()],
    )


def test_coding_result_roundtrip():
    result = CodingResult(
        document_id="note_x",
        diagnoses=[_sample_suggestion("E11.9")],
        procedures=[],
        warnings=[
            Warning(
                type=WarningType.MISSING_INFORMATION,
                severity=WarningSeverity.INFO,
                message="Specificity warning",
                refs=["E11.9"],
            )
        ],
        metadata=RunMetadata(
            trace_id="abc123",
            model_ids={"coder": "gpt-4o-2024-08-06"},
            pipeline_version="0.1.0",
            temperature=0.0,
            config_hash="deadbeef00000000",
        ),
    )
    payload = result.model_dump_json()
    again = CodingResult.model_validate_json(payload)
    assert again.diagnoses[0].code == "E11.9"
    assert again.diagnoses[0].reviewer_decision == ReviewerDecision.SUGGESTED
    assert json.loads(payload)["warnings"][0]["type"] == "missing_information"


def test_confidence_must_be_in_unit_interval():
    base = _sample_suggestion().model_dump()
    with pytest.raises(ValidationError):
        CodeSuggestion.model_validate({**base, "confidence": 1.4})
    with pytest.raises(ValidationError):
        CodeSuggestion.model_validate({**base, "confidence": -0.01})


def test_extra_fields_are_rejected():
    """Closed schema is the audit-trail promise — strict extras prevent silent drift."""
    with pytest.raises(ValidationError):
        ExtractedFact.model_validate(
            {
                "text": "x",
                "normalized_term": "x",
                "assertion_status": "present",
                "start_offset": 0,
                "end_offset": 1,
                "kind": "diagnosis",
                "BOGUS": True,  # not in schema
            }
        )
