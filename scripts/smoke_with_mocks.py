"""End-to-end smoke run on the real ICD-10 index, with canned LLM responses.

No API key required. Demonstrates that the full pipeline produces a valid
CodingResult against the real 75k-code catalog. Useful for reviewers who want
to see output without provisioning an LLM key.
"""

from __future__ import annotations

import json
from pathlib import Path

from medcoder.logging_setup import configure_logging
from medcoder.pipeline import MockResponses
from medcoder.pipeline import run as run_pipeline

NOTE_PATH = Path("data/notes/note_01_outpatient_diabetes.txt")

# Canned LLM responses for the diabetes follow-up note.
# In a real run these would be produced by the LLM agents.
EXTRACTION_FACTS = {
    "facts": [
        {
            "text": "type 2 diabetes mellitus",
            "normalized_term": "type 2 diabetes mellitus with polyneuropathy",
            "assertion_status": "present",
            "start_offset": 0,  # overwritten below to the real offset
            "end_offset": 24,
            "section": "assessment",
            "kind": "diagnosis",
        },
        {
            "text": "essential hypertension",
            "normalized_term": "essential hypertension",
            "assertion_status": "present",
            "start_offset": 0,
            "end_offset": 22,
            "section": "assessment",
            "kind": "diagnosis",
        },
        {
            "text": "diabetic nephropathy",
            "normalized_term": "type 2 diabetes mellitus with diabetic nephropathy",
            "assertion_status": "present",
            "start_offset": 0,
            "end_offset": 20,
            "section": "assessment",
            "kind": "diagnosis",
        },
        {
            "text": "obesity",
            "normalized_term": "obesity unspecified",
            "assertion_status": "present",
            "start_offset": 0,
            "end_offset": 7,
            "section": "assessment",
            "kind": "diagnosis",
        },
        {
            "text": "comprehensive diabetic foot examination",
            "normalized_term": "comprehensive diabetic foot examination",
            "assertion_status": "present",
            "start_offset": 0,
            "end_offset": 39,
            "section": "objective",
            "kind": "procedure",
        },
    ]
}

CODER_ASSIGNMENTS = {
    "assignments": [
        {
            "fact_index": 0,
            "choices": [
                {"code": "E11.42", "confidence": 0.86,
                 "rationale": "Assessment names T2DM with diabetic polyneuropathy; monofilament sensation reduced bilaterally."}
            ],
        },
        {
            "fact_index": 1,
            "choices": [
                {"code": "I10", "confidence": 0.91,
                 "rationale": "Assessment cites essential hypertension explicitly."}
            ],
        },
        {
            "fact_index": 2,
            "choices": [
                {"code": "E11.21", "confidence": 0.78,
                 "rationale": "Diabetic nephropathy with microalbuminuria documented."}
            ],
        },
        {
            "fact_index": 3,
            "choices": [
                {"code": "E66.9", "confidence": 0.72,
                 "rationale": "BMI 31.4; no class specified — unspecified is the best match."}
            ],
        },
        {
            "fact_index": 4,
            "choices": [
                {"code": "9T0012", "confidence": 0.90,
                 "rationale": "Comprehensive diabetic foot examination performed today (Objective)."}
            ],
        },
    ]
}

AUDITOR_VERDICTS = {
    "verdicts": [
        {"pair_index": i, "agree": True, "note": ""}
        for i in range(5)
    ]
}


def main() -> None:
    configure_logging(level="WARNING", json_mode=False)
    text = NOTE_PATH.read_text()

    # Anchor offsets so reconcile_assertion is happy
    def _anchor(facts, src):
        for f in facts["facts"]:
            idx = src.lower().find(f["text"].lower())
            if idx >= 0:
                f["start_offset"] = idx
                f["end_offset"] = idx + len(f["text"])
        return facts

    extraction = _anchor(EXTRACTION_FACTS, text)

    res = run_pipeline(
        text,
        document_id="smoke_note_01",
        mocks=MockResponses(
            extraction=json.dumps(extraction),
            coder=json.dumps(CODER_ASSIGNMENTS),
            auditor=json.dumps(AUDITOR_VERDICTS),
        ),
    ).coding_result

    print(json.dumps(res.model_dump(mode="json"), indent=2, default=str))


if __name__ == "__main__":
    main()
