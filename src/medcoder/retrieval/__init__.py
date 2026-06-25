"""Hybrid retrieval over the ICD-10 and CPT catalogs.

Three sub-modules compose into the pipeline's pre-constraint:
  - :mod:`catalog` — loaders for the CDC ICD-10 file + synthetic CPT CSV.
  - :mod:`vector`  — dense FAISS index over sentence-transformer embeddings.
  - :mod:`lexical` — BM25 index for exact clinical phrasing.

The public surface is :func:`hybrid.get_retriever`, which lazily builds (or
loads cached) indexes and returns a :class:`hybrid.HybridRetriever` that fuses
dense + lexical hits via Reciprocal Rank Fusion.
"""
