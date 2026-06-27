"""Retrieval — catalog loading, BM25 sanity, and recall@k on a small in-memory catalog.

Avoids the full 75k ICD-10 build (which is exercised by the e2e tests) so this
suite runs fast and offline.
"""

from __future__ import annotations

import pytest

from medcoder.retrieval.catalog import CatalogEntry
from medcoder.retrieval.hybrid import HybridRetriever
from medcoder.retrieval.lexical import LexicalIndex, tokenize
from medcoder.schemas import CodeSystem

_SAMPLE = [
    CatalogEntry("E11.9", CodeSystem.ICD10, "Type 2 diabetes mellitus without complications"),
    CatalogEntry(
        "E11.42", CodeSystem.ICD10, "Type 2 diabetes mellitus with diabetic polyneuropathy"
    ),
    CatalogEntry("E10.9", CodeSystem.ICD10, "Type 1 diabetes mellitus without complications"),
    CatalogEntry("I10", CodeSystem.ICD10, "Essential (primary) hypertension"),
    CatalogEntry("J18.9", CodeSystem.ICD10, "Pneumonia, unspecified organism"),
    CatalogEntry(
        "I21.09", CodeSystem.ICD10, "ST elevation myocardial infarction of other anterior wall"
    ),
    CatalogEntry("E66.9", CodeSystem.ICD10, "Obesity, unspecified"),
]


def test_tokenize_lowercases_and_splits():
    assert tokenize("Type 2 Diabetes!") == ["type", "2", "diabetes"]


def test_bm25_finds_exact_term():
    idx = LexicalIndex()
    idx.build(_SAMPLE)
    hits = idx.search("type 2 diabetes mellitus", top_k=3)
    top_codes = {_SAMPLE[h.catalog_index].code for h in hits}
    assert "E11.9" in top_codes


@pytest.mark.slow
def test_hybrid_retriever_returns_diabetes_for_t2dm_query():
    """End-to-end hybrid on the small sample (loads sentence-transformers)."""
    pytest.importorskip("sentence_transformers")
    r = HybridRetriever(CodeSystem.ICD10, _SAMPLE)
    r.build()
    hits = r.search("type 2 diabetes mellitus without complications", top_k=3)
    codes = [h.code for h in hits]
    assert "E11.9" in codes
    # Should outrank Type 1 for a Type 2 query
    assert codes.index("E11.9") < codes.index("E10.9")


@pytest.mark.slow
def test_hybrid_search_populates_fused_rank():
    """Each returned candidate carries its 1-based post-fusion rank (feeds confidence)."""
    pytest.importorskip("sentence_transformers")
    r = HybridRetriever(CodeSystem.ICD10, _SAMPLE)
    r.build()
    hits = r.search("type 2 diabetes mellitus", top_k=3)
    assert [h.fused_rank for h in hits] == [1, 2, 3]
