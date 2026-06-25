"""Dense semantic index — sentence-transformers embeddings stored in FAISS.

Default embedder is the small general-purpose MiniLM — Plan.md §3 marks this as a
demo compromise; production swap is SapBERT/PubMedBERT.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from ..logging_setup import get_logger
from .catalog import CatalogEntry

log = get_logger(__name__)


@dataclass
class VectorHit:
    catalog_index: int
    score: float  # cosine similarity in [-1, 1] (we IndexFlatIP on L2-normalised vectors)


class VectorIndex:
    """Single-system FAISS index over `description` embeddings.

    Persisted as two files: `<prefix>.faiss` (the index) and `<prefix>.npy`
    (embeddings; kept around so we can rebuild the index without re-embedding).
    """

    def __init__(self, embedder_name: str):
        self.embedder_name = embedder_name
        self._embedder = None  # lazy-loaded
        self._index: faiss.Index | None = None
        self._dim: int | None = None

    # ---- model ---------------------------------------------------------

    def _load_embedder(self):
        if self._embedder is None:
            # Lazy import keeps `medcoder --help` instantaneous
            from sentence_transformers import SentenceTransformer

            log.info("loading_embedder", extra={"model": self.embedder_name})
            self._embedder = SentenceTransformer(self.embedder_name)
            # Newer sentence-transformers renamed this — keep both for compatibility.
            dim_fn = getattr(
                self._embedder,
                "get_embedding_dimension",
                self._embedder.get_sentence_embedding_dimension,
            )
            self._dim = int(dim_fn())
        return self._embedder

    def _encode(self, texts: Sequence[str], batch_size: int = 256) -> np.ndarray:
        model = self._load_embedder()
        # `normalize_embeddings=True` makes inner-product equivalent to cosine,
        # which is what `IndexFlatIP` expects. Load-bearing for retrieval
        # correctness. Source: https://sbert.net/docs/package_reference/SentenceTransformer.html#sentence_transformers.SentenceTransformer.encode
        vecs = model.encode(
            list(texts),
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vecs.astype("float32")

    # ---- build / persist -----------------------------------------------

    def build(self, entries: Sequence[CatalogEntry]) -> None:
        if not entries:
            raise ValueError("Cannot build vector index over an empty catalog.")
        embeddings = self._encode([e.description for e in entries])
        self._dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(self._dim)
        self._index.add(embeddings)

    def save(self, prefix: Path) -> None:
        prefix.parent.mkdir(parents=True, exist_ok=True)
        if self._index is None:
            raise RuntimeError("Build the index before saving.")
        faiss.write_index(self._index, str(prefix.with_suffix(".faiss")))
        log.info("vector_index_saved", extra={"prefix": str(prefix), "n": self._index.ntotal})

    def load(self, prefix: Path) -> None:
        self._index = faiss.read_index(str(prefix.with_suffix(".faiss")))
        self._dim = self._index.d

    # ---- query ----------------------------------------------------------

    def search(self, query: str, top_k: int) -> list[VectorHit]:
        if self._index is None:
            raise RuntimeError("Vector index not loaded.")
        q = self._encode([query])
        scores, idxs = self._index.search(q, top_k)
        return [
            VectorHit(catalog_index=int(i), score=float(s))
            for s, i in zip(scores[0], idxs[0], strict=True)
            if i >= 0
        ]
