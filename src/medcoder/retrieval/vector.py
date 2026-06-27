"""Dense semantic index — embeddings stored in FAISS.

The embedder is pluggable (see embedders.py). Default is the small general-purpose
local MiniLM — a demo compromise; the production swap for
clinical text is a domain embedder such as SapBERT/PubMedBERT, and a hosted OpenAI
backend is available opt-in. All backends emit L2-normalized vectors so the
`IndexFlatIP` below is cosine similarity.

Switching embedders changes the vector dimension, so each saved index carries a
`<prefix>.meta.json` sidecar recording the embedder name + dim; `load()` refuses a
stale index built with a different embedder, preventing silent dim-mismatch garbage.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from ..logging_setup import get_logger
from .catalog import CatalogEntry
from .embedders import make_embedder

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
        # Backend is chosen by name (MiniLM / SapBERT / OpenAI …); model weights or
        # client are lazy-loaded inside the backend, keeping `medcoder --help` instant.
        self._embedder = make_embedder(embedder_name)
        self._index: faiss.Index | None = None
        self._dim: int | None = None

    # ---- model ---------------------------------------------------------

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        # Every backend returns L2-normalized float32 (see embedders.py), so
        # inner-product on `IndexFlatIP` is cosine similarity — load-bearing for
        # retrieval correctness.
        return self._embedder.encode(texts)

    # ---- build / persist -----------------------------------------------

    def build(self, entries: Sequence[CatalogEntry]) -> None:
        if not entries:
            raise ValueError("Cannot build vector index over an empty catalog.")
        embeddings = self._encode([e.description for e in entries])
        self._dim = embeddings.shape[1]
        # IndexFlatIP = inner product; on the L2-normalized vectors our embedders emit
        # this equals cosine similarity.
        # Source: https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances — Verified 2026-06-27
        self._index = faiss.IndexFlatIP(self._dim)
        self._index.add(embeddings)

    def save(self, prefix: Path) -> None:
        prefix.parent.mkdir(parents=True, exist_ok=True)
        if self._index is None:
            raise RuntimeError("Build the index before saving.")
        faiss.write_index(self._index, str(prefix.with_suffix(".faiss")))
        # Sidecar records which embedder built this index so load() can refuse a
        # stale index after an embedder swap (different dim → garbage retrieval).
        prefix.with_suffix(".meta.json").write_text(
            json.dumps({"embedder": self.embedder_name, "dim": self._dim})
        )
        log.info("vector_index_saved", extra={"prefix": str(prefix), "n": self._index.ntotal})

    def load(self, prefix: Path) -> None:
        meta_path = prefix.with_suffix(".meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("embedder") != self.embedder_name:
                raise RuntimeError(
                    f"Index at {prefix} was built with embedder {meta.get('embedder')!r} "
                    f"but the current config uses {self.embedder_name!r}. Rebuild it: "
                    "`make build-index ARGS='--force'`."
                )
        else:
            # Legacy index without a sidecar — can't verify the embedder. Warn and
            # trust the config rather than hard-failing an otherwise-working index.
            log.warning("vector_index_no_meta", extra={"prefix": str(prefix)})
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
