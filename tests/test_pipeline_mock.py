"""End-to-end pipeline test with mocked LLM responses.

This test exercises ingest → extract → retrieve → code → audit → rules →
assemble on a synthetic note, replacing every LLM call with canned JSON. It
catches integration breakage even when no API key is present.

Note: it still hits the *real* retrieval index — it relies on a small test
catalog injected into the hybrid retriever cache.
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
def small_icd_catalog():
    """Inject a tiny ICD-10 catalog into the retriever cache for fast offline tests."""
    pytest.importorskip("sentence_transformers")
    entries = [
        CatalogEntry("E11.9", CodeSystem.ICD10, "Type 2 diabetes mellitus without complications"),
        CatalogEntry(
            "E11.42", CodeSystem.ICD10, "Type 2 diabetes mellitus with diabetic polyneuropathy"
        ),
        CatalogEntry("I10", CodeSystem.ICD10, "Essential (primary) hypertension"),
        CatalogEntry("E66.9", CodeSystem.ICD10, "Obesity, unspecified"),
    ]
    r = HybridRetriever(CodeSystem.ICD10, entries)
    r.build()
    hybrid_mod._CACHE[CodeSystem.ICD10.value] = r
    yield entries
    hybrid_mod.reset_cache()


@pytest.fixture
def small_cpt_catalog():
    pytest.importorskip("sentence_transformers")
    entries = [
        CatalogEntry(
            "9E0002",
            CodeSystem.CPT,
            "[SYNTHETIC] Office visit established patient moderate complexity",
        ),
        CatalogEntry(
            "9T0012", CodeSystem.CPT, "[SYNTHETIC] Comprehensive diabetic foot examination"
        ),
    ]
    r = HybridRetriever(CodeSystem.CPT, entries)
    r.build()
    hybrid_mod._CACHE[CodeSystem.CPT.value] = r
    yield entries


@pytest.mark.slow
def test_pipeline_drops_offlist_coder_codes(small_icd_catalog):
    """Anti-hallucination guarantee: a coder code not in the retrieval whitelist
    must be silently dropped, never propagated into the final CodingResult.

    This is the structural property the whole 'retrieve-then-constrain' design
    rests on. If a regression removes the filter at
    code_assign.assign_codes, this test would catch it.
    """
    note = "Assessment: Type 2 diabetes mellitus."
    extraction = {
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
    # The coder returns two choices — one IS in the whitelist (E11.9) and one ISN'T
    # (Z99.999 is a real-looking but fictitious code never retrieved here).
    coder = {
        "assignments": [
            {
                "fact_index": 0,
                "choices": [
                    {
                        "code": "Z99.999",
                        "confidence": 0.95,
                        "rationale": "Hallucinated — would slip through without the whitelist guard.",
                    },
                    {
                        "code": "E11.9",
                        "confidence": 0.90,
                        "rationale": "Real candidate from the whitelist.",
                    },
                ],
            }
        ]
    }
    auditor = {"verdicts": [{"pair_index": 0, "agree": True, "note": ""}]}

    res = run_pipeline(
        note,
        document_id="t_offlist",
        mocks=MockResponses(
            extraction=json.dumps(extraction),
            coder=json.dumps(coder),
            auditor=json.dumps(auditor),
        ),
    ).coding_result

    codes = {s.code for s in res.diagnoses}
    assert "E11.9" in codes, "in-whitelist code should be assigned"
    assert "Z99.999" not in codes, "out-of-whitelist hallucination MUST be dropped"


@pytest.mark.slow
def test_pipeline_runs_with_mock_llm(small_icd_catalog, small_cpt_catalog):
    note = (
        "Outpatient follow-up.\n"
        "Assessment:\n"
        "1. Type 2 diabetes mellitus.\n"
        "2. Essential hypertension.\n"
    )
    # Extraction returns two present-status diagnoses.
    extraction = {
        "facts": [
            {
                "text": "Type 2 diabetes mellitus",
                "normalized_term": "type 2 diabetes mellitus",
                "assertion_status": "present",
                "start_offset": note.index("Type 2 diabetes mellitus"),
                "end_offset": note.index("Type 2 diabetes mellitus")
                + len("Type 2 diabetes mellitus"),
                "section": "assessment",
                "kind": "diagnosis",
            },
            {
                "text": "Essential hypertension",
                "normalized_term": "essential hypertension",
                "assertion_status": "present",
                "start_offset": note.index("Essential hypertension"),
                "end_offset": note.index("Essential hypertension") + len("Essential hypertension"),
                "section": "assessment",
                "kind": "diagnosis",
            },
        ]
    }
    coder = {
        "assignments": [
            {
                "fact_index": 0,
                "choices": [{"code": "E11.9", "confidence": 0.86, "rationale": "T2DM stated."}],
            },
            {
                "fact_index": 1,
                "choices": [
                    {"code": "I10", "confidence": 0.91, "rationale": "Essential HTN stated."}
                ],
            },
        ]
    }
    # Auditor agrees with both. (Selective verification: ours doesn't fire for high-conf
    # ICD codes by default, so this string is exercised only if the threshold falls;
    # supply it defensively.)
    auditor = {
        "verdicts": [
            {"pair_index": 0, "agree": True, "note": ""},
            {"pair_index": 1, "agree": True, "note": ""},
        ]
    }

    res = run_pipeline(
        note,
        document_id="t1",
        mocks=MockResponses(
            extraction=json.dumps(extraction),
            coder=json.dumps(coder),
            auditor=json.dumps(auditor),
        ),
    ).coding_result

    codes = {s.code for s in res.diagnoses}
    assert "E11.9" in codes
    assert "I10" in codes
    assert all(s.confidence > 0.0 for s in res.diagnoses)
    # RunMetadata fingerprint present
    assert res.metadata.config_hash
    assert res.metadata.metrics.total_latency_ms > 0
    # No CPT in this note
    assert res.procedures == []


@pytest.mark.slow
def test_extraction_encounter_type_overrides_heuristic(small_icd_catalog):
    """The extraction LLM's encounter_type wins over the keyword heuristic.

    The note has no inpatient keywords (heuristic → unknown), but the LLM reports
    'inpatient'; the run metadata must reflect the LLM's whole-note call.
    """
    note = "Assessment: Type 2 diabetes mellitus."
    extraction = {
        "encounter_type": "inpatient",
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
        ],
    }
    coder = {
        "assignments": [
            {
                "fact_index": 0,
                "choices": [{"code": "E11.9", "confidence": 0.9, "rationale": "T2DM."}],
            }
        ]
    }
    auditor = {"verdicts": [{"pair_index": 0, "agree": True, "note": ""}]}

    res = run_pipeline(
        note,
        document_id="t_enc",
        mocks=MockResponses(
            extraction=json.dumps(extraction),
            coder=json.dumps(coder),
            auditor=json.dumps(auditor),
        ),
    ).coding_result
    assert res.metadata.encounter_type.value == "inpatient"


def test_query_expansion_issues_a_search_per_term(monkeypatch):
    """_retrieve_for_facts must query the normalized_term AND every query_term, in order."""
    from medcoder.pipeline import _retrieve_for_facts
    from medcoder.schemas import ExtractedFact

    calls: list[str] = []

    class StubRetriever:
        def search(self, q, top_k=None):
            calls.append(q)
            return []

    monkeypatch.setattr("medcoder.pipeline.get_retriever", lambda system: StubRetriever())

    fact = ExtractedFact(
        text="MI",
        normalized_term="myocardial infarction",
        query_terms=["MI", "heart attack"],
        assertion_status="present",
        start_offset=0,
        end_offset=2,
        kind="diagnosis",
    )
    _retrieve_for_facts([fact])
    assert calls == ["myocardial infarction", "MI", "heart attack"]


def test_query_expansion_skips_blank_terms_and_empty_list(monkeypatch):
    """Empty query_terms → only the normalized_term is queried; blank terms are skipped."""
    from medcoder.pipeline import _retrieve_for_facts
    from medcoder.schemas import ExtractedFact

    calls: list[str] = []

    class StubRetriever:
        def search(self, q, top_k=None):
            calls.append(q)
            return []

    monkeypatch.setattr("medcoder.pipeline.get_retriever", lambda system: StubRetriever())

    fact_empty = ExtractedFact(
        text="x",
        normalized_term="hypertension",
        query_terms=[],
        assertion_status="present",
        start_offset=0,
        end_offset=1,
        kind="diagnosis",
    )
    fact_blank = ExtractedFact(
        text="y",
        normalized_term="diabetes",
        query_terms=["", "  "],
        assertion_status="present",
        start_offset=0,
        end_offset=1,
        kind="diagnosis",
    )
    _retrieve_for_facts([fact_empty, fact_blank])
    assert calls == ["hypertension", "diabetes"]
