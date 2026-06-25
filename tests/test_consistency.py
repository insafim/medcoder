"""Reproducibility: the same input + same mocked LLM responses must produce
identical CodingResult bodies (modulo run-specific metadata: trace_id, latency,
timestamp).

If this test starts to flake, *something* in the deterministic stages
(ingestion, retrieval order, rule evaluation, confidence blending) has gained
a non-determinism — fix the determinism, not the test.
"""

from __future__ import annotations

import json

import pytest

from medcoder.pipeline import MockResponses
from medcoder.pipeline import run as run_pipeline
from medcoder.retrieval import hybrid as hybrid_mod
from medcoder.retrieval.catalog import CatalogEntry
from medcoder.retrieval.hybrid import HybridRetriever
from medcoder.schemas import CodeSystem


@pytest.fixture
def diabetes_catalog():
    pytest.importorskip("sentence_transformers")
    entries = [
        CatalogEntry("E11.9", CodeSystem.ICD10, "Type 2 diabetes mellitus without complications"),
        CatalogEntry("E10.9", CodeSystem.ICD10, "Type 1 diabetes mellitus without complications"),
    ]
    r = HybridRetriever(CodeSystem.ICD10, entries)
    r.build()
    hybrid_mod._CACHE[CodeSystem.ICD10.value] = r
    yield
    hybrid_mod.reset_cache()


@pytest.mark.slow
def test_two_runs_match_on_deterministic_fields(diabetes_catalog):
    note = "Assessment: Type 2 diabetes mellitus."
    mocks = MockResponses(
        extraction=json.dumps(
            {
                "facts": [
                    {
                        "text": "Type 2 diabetes mellitus",
                        "normalized_term": "type 2 diabetes mellitus",
                        "assertion_status": "present",
                        "start_offset": note.index("Type 2"),
                        "end_offset": note.index("Type 2") + len("Type 2 diabetes mellitus"),
                        "section": "assessment",
                        "kind": "diagnosis",
                    }
                ]
            }
        ),
        coder=json.dumps(
            {
                "assignments": [
                    {
                        "fact_index": 0,
                        "choices": [{"code": "E11.9", "confidence": 0.9, "rationale": "stated"}],
                    }
                ]
            }
        ),
        auditor=json.dumps({"verdicts": [{"pair_index": 0, "agree": True, "note": ""}]}),
    )
    a = run_pipeline(note, document_id="d", mocks=mocks).coding_result
    b = run_pipeline(note, document_id="d", mocks=mocks).coding_result

    def _strip_volatile(payload: dict) -> dict:
        meta = payload["metadata"]
        meta["trace_id"] = "*"
        meta["timestamp"] = "*"
        meta["metrics"]["total_latency_ms"] = 0
        meta["metrics"]["stage_latency_ms"] = {}
        return payload

    assert _strip_volatile(a.model_dump(mode="json")) == _strip_volatile(b.model_dump(mode="json"))
