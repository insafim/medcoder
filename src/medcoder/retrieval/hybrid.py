"""Hybrid retriever — dense (FAISS) + lexical (BM25) fused via Reciprocal Rank Fusion.

RRF is the dominant hybrid-fusion choice in IR because it needs **no score
calibration** between heterogeneous scorers (cosine ≠ BM25). Each ranker
contributes ``1 / (k + rank)``; fused scores are summed.

Reference: Cormack, Clarke & Büttcher (2009), "Reciprocal Rank Fusion outperforms
Condorcet and individual rank learning methods."
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..config import get_settings
from ..logging_setup import get_logger
from ..schemas import CandidateCode, CodeSystem
from .catalog import CatalogEntry, load_cpt, load_icd10
from .lexical import LexicalIndex
from .vector import VectorIndex

log = get_logger(__name__)


def _index_prefix(index_dir: Path, system: CodeSystem) -> Path:
    return index_dir / {"ICD-10-CM": "icd10", "CPT": "cpt"}[system.value]


class HybridRetriever:
    """One instance per code system; the pipeline holds two (ICD-10 and CPT)."""

    def __init__(self, system: CodeSystem, entries: Sequence[CatalogEntry]) -> None:
        self.system = system
        self.entries: list[CatalogEntry] = list(entries)
        self.vector = VectorIndex(get_settings().embedder)
        self.lexical = LexicalIndex()

    # ---- build / persist -----------------------------------------------

    def build(self) -> None:
        log.info("hybrid_build_start", extra={"system": self.system.value, "n": len(self.entries)})
        self.vector.build(self.entries)
        self.lexical.build(self.entries)

    def save(self, index_dir: Path) -> None:
        prefix = _index_prefix(index_dir, self.system)
        self.vector.save(prefix)
        self.lexical.save(prefix)

    def load(self, index_dir: Path) -> None:
        prefix = _index_prefix(index_dir, self.system)
        self.vector.load(prefix)
        self.lexical.load(prefix)

    # ---- query ----------------------------------------------------------

    def search(self, query: str, top_k: int | None = None) -> list[CandidateCode]:
        s = get_settings()
        top_k = top_k or s.retrieval_top_k

        dense_hits = self.vector.search(query, s.retrieval_dense_n)
        lex_hits = self.lexical.search(query, s.retrieval_lexical_n)

        # ---- Reciprocal Rank Fusion -----------------------------------
        fused: dict[int, dict[str, float | int | None]] = {}
        for rank, hit in enumerate(dense_hits):
            fused.setdefault(
                hit.catalog_index,
                {"score": 0.0, "dense_rank": None, "lex_rank": None},
            )
            fused[hit.catalog_index]["score"] += 1.0 / (s.rrf_k + rank + 1)
            fused[hit.catalog_index]["dense_rank"] = rank + 1
        for rank, hit in enumerate(lex_hits):
            fused.setdefault(
                hit.catalog_index,
                {"score": 0.0, "dense_rank": None, "lex_rank": None},
            )
            fused[hit.catalog_index]["score"] += 1.0 / (s.rrf_k + rank + 1)
            fused[hit.catalog_index]["lex_rank"] = rank + 1

        ranked = sorted(fused.items(), key=lambda kv: -kv[1]["score"])[:top_k]
        out: list[CandidateCode] = []
        for pos, (idx, info) in enumerate(ranked, start=1):
            entry = self.entries[idx]
            out.append(
                CandidateCode(
                    code=entry.code,
                    system=entry.system,
                    description=entry.description,
                    retrieval_score=float(info["score"]),
                    dense_rank=info["dense_rank"],
                    lexical_rank=info["lex_rank"],
                    fused_rank=pos,
                )
            )
        return out


# ---- module-level catalog cache (avoid re-loading 75k ICD-10 per request) ---


_CACHE: dict[str, HybridRetriever] = {}


def get_retriever(system: CodeSystem) -> HybridRetriever:
    """Load-or-build the persistent index for ``system``."""
    key = system.value
    if key in _CACHE:
        return _CACHE[key]
    s = get_settings()
    if system == CodeSystem.ICD10:
        entries = load_icd10(s.icd10_catalog)
    elif system == CodeSystem.CPT:
        entries = load_cpt(s.cpt_catalog)
    else:
        raise ValueError(f"Unknown code system: {system}")
    retr = HybridRetriever(system, entries)
    prefix = _index_prefix(s.index_dir, system)
    if prefix.with_suffix(".faiss").exists() and prefix.with_suffix(".bm25.pkl").exists():
        retr.load(s.index_dir)
        log.info("retriever_loaded", extra={"system": key, "n": len(entries)})
    else:
        log.info("retriever_building", extra={"system": key, "n": len(entries)})
        retr.build()
        retr.save(s.index_dir)
    _CACHE[key] = retr
    return retr


def reset_cache() -> None:
    """Test hook."""
    _CACHE.clear()
