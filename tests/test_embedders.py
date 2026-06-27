"""Tests for the pluggable embedder backends and the index dim-mismatch guard.

All fast: the factory and the OpenAI backend are exercised without loading a real
sentence-transformers model and without any network (litellm.embedding is mocked).
"""

from __future__ import annotations

import json

import faiss
import numpy as np
import pytest

from medcoder.retrieval.embedders import (
    OpenAIEmbedder,
    SentenceTransformerEmbedder,
    _l2_normalize,
    make_embedder,
)
from medcoder.retrieval.vector import VectorIndex

# ---- factory routing -----------------------------------------------------


def test_factory_routes_local_names_to_sentence_transformers():
    assert isinstance(
        make_embedder("sentence-transformers/all-MiniLM-L6-v2"), SentenceTransformerEmbedder
    )
    # a domain model (SapBERT) also loads through the local backend
    assert isinstance(
        make_embedder("cambridgeltl/SapBERT-from-PubMedBERT-fulltext"),
        SentenceTransformerEmbedder,
    )


@pytest.mark.parametrize("name", ["openai/text-embedding-3-large", "text-embedding-3-small"])
def test_factory_routes_openai_names(name):
    assert isinstance(make_embedder(name), OpenAIEmbedder)


# ---- normalization -------------------------------------------------------


def test_l2_normalize_makes_unit_rows_and_guards_zero():
    v = _l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]], dtype="float32"))
    assert v.dtype == np.float32
    assert np.isclose(np.linalg.norm(v[0]), 1.0)  # 3,4 → unit
    assert np.isclose(np.linalg.norm(v[1]), 0.0)  # zero vector stays zero (no div-by-0)


# ---- OpenAI backend (mocked) ---------------------------------------------


def _fake_embedding_response(texts, dim=4):
    """Mimic the shape of litellm.embedding(...)['data']."""
    return {"data": [{"embedding": [float(i + 1)] * dim} for i, _ in enumerate(texts)]}


def test_openai_encode_returns_normalized_float32(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    import litellm

    monkeypatch.setattr(litellm, "embedding", lambda model, input: _fake_embedding_response(input))
    out = OpenAIEmbedder("openai/text-embedding-3-large").encode(["a", "b", "c"])
    assert out.dtype == np.float32
    assert out.shape == (3, 4)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)  # all rows unit-normalized


def test_openai_encode_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIEmbedder("openai/text-embedding-3-large").encode(["x"])


def test_openai_dim_from_table_needs_no_network():
    # No OPENAI_API_KEY, no litellm mock — .dim must resolve from the known table.
    assert OpenAIEmbedder("openai/text-embedding-3-large").dim == 3072
    assert OpenAIEmbedder("text-embedding-3-small").dim == 1536


# ---- index dim-mismatch guard --------------------------------------------


def _write_tiny_index(prefix, dim=4):
    idx = faiss.IndexFlatIP(dim)
    idx.add(np.zeros((1, dim), dtype="float32"))
    faiss.write_index(idx, str(prefix.with_suffix(".faiss")))


def test_load_rejects_index_built_with_a_different_embedder(tmp_path):
    prefix = tmp_path / "icd10"
    _write_tiny_index(prefix)
    prefix.with_suffix(".meta.json").write_text(
        json.dumps({"embedder": "sentence-transformers/all-MiniLM-L6-v2", "dim": 384})
    )
    vi = VectorIndex("openai/text-embedding-3-large")  # different embedder than the sidecar
    with pytest.raises(RuntimeError, match="Rebuild"):
        vi.load(prefix)


def test_load_without_sidecar_warns_but_succeeds(tmp_path):
    prefix = tmp_path / "icd10"
    _write_tiny_index(prefix)  # legacy index, no .meta.json
    vi = VectorIndex("sentence-transformers/all-MiniLM-L6-v2")
    vi.load(prefix)  # must not raise
    assert vi._index is not None
