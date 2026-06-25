"""Lexical BM25 index over catalog descriptions.

BM25 catches exact clinical phrasing ("type 2 diabetes mellitus") that dense
embeddings sometimes paraphrase past. Fused with the vector index via RRF.
"""

from __future__ import annotations

import pickle
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi

from .catalog import CatalogEntry

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


@dataclass
class LexicalHit:
    catalog_index: int
    score: float


class LexicalIndex:
    """BM25 (Okapi) lexical index over catalog descriptions.

    Uses ``rank_bm25.BM25Okapi`` with library defaults (k1=1.5, b=0.75) — the
    standard Okapi BM25 parameters per Robertson & Zaragoza (2009). Persisted
    as a pickle alongside the FAISS index file.
    """

    def __init__(self):
        self._bm25: BM25Okapi | None = None
        self._corpus_size: int = 0

    def build(self, entries: Sequence[CatalogEntry]) -> None:
        tokenised = [tokenize(e.description) for e in entries]
        # rank-bm25 requires non-empty docs; pad rare empties so indices line up.
        tokenised = [doc if doc else ["__empty__"] for doc in tokenised]
        self._bm25 = BM25Okapi(tokenised)
        self._corpus_size = len(tokenised)

    def save(self, prefix: Path) -> None:
        if self._bm25 is None:
            raise RuntimeError("Build first.")
        prefix.parent.mkdir(parents=True, exist_ok=True)
        with prefix.with_suffix(".bm25.pkl").open("wb") as fh:
            pickle.dump({"bm25": self._bm25, "size": self._corpus_size}, fh)

    def load(self, prefix: Path) -> None:
        with prefix.with_suffix(".bm25.pkl").open("rb") as fh:
            obj = pickle.load(fh)
        self._bm25 = obj["bm25"]
        self._corpus_size = obj["size"]

    def search(self, query: str, top_k: int) -> list[LexicalHit]:
        if self._bm25 is None:
            raise RuntimeError("Lexical index not loaded.")
        toks = tokenize(query) or ["__empty__"]
        scores = self._bm25.get_scores(toks)
        # argpartition for speed on the long ICD-10 catalog
        k = min(top_k, self._corpus_size)
        top_idx = scores.argpartition(-k)[-k:]
        ordered = sorted(top_idx, key=lambda i: -scores[i])
        return [LexicalHit(catalog_index=int(i), score=float(scores[i])) for i in ordered]
