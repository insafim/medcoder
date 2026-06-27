"""Pluggable dense-embedding backends for the vector retriever.

The dense retriever (vector.py) embeds two kinds of *short clinical strings*: the
catalog code **descriptions** at build time, and each extracted clinical **term**
at query time (never the raw note — extraction distils it first). Every backend
here must turn such strings into **L2-normalized float32** vectors so FAISS
`IndexFlatIP` computes cosine similarity.

Backends:
  - `SentenceTransformerEmbedder` — local, keyless, offline. The MiniLM default
    lives here; the production-grade clinical upgrade (SapBERT — trained for
    exactly this mention→concept task — or PubMedBERT) loads through the same
    path with no code change, just `MEDCODER_EMBEDDER`.
  - `OpenAIEmbedder` — hosted, opt-in. Needs `OPENAI_API_KEY` at *build* time, so
    it is deliberately not the default (it would break the keyless clone→build
    path). No quality claim is made over MiniLM here — it is a provider option.

Because different backends produce different vector dimensions, the on-disk index
carries an embedder/dim sidecar that vector.py checks before loading, preventing
silent dimension-mismatch corruption when someone swaps embedders without
rebuilding.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from ..logging_setup import get_logger

log = get_logger(__name__)


@runtime_checkable
class Embedder(Protocol):
    """A dense-embedding backend: short strings → L2-normalized float32 vectors."""

    name: str

    @property
    def dim(self) -> int:
        """Embedding dimensionality (used by the index dim-mismatch guard)."""
        ...

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Embed `texts` into an (n, dim) L2-normalized float32 array."""
        ...


def _l2_normalize(vecs: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalization so inner product equals cosine similarity."""
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # guard against a zero vector → division by zero
    return (vecs / norms).astype("float32")


class SentenceTransformerEmbedder:
    """Local sentence-transformers backend (MiniLM default; SapBERT/PubMedBERT swap in here).

    sentence-transformers normalizes for us (`normalize_embeddings=True`), which is
    load-bearing for retrieval correctness — `IndexFlatIP` only equals cosine on
    unit vectors.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._model = None  # lazy-loaded — keeps `medcoder --help` instant
        self._dim: int | None = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy/heavy import

            log.info(
                "loading_embedder", extra={"model": self.name, "backend": "sentence_transformers"}
            )
            self._model = SentenceTransformer(self.name)
            # Newer sentence-transformers renamed this accessor — accept both.
            dim_fn = getattr(
                self._model,
                "get_embedding_dimension",
                self._model.get_sentence_embedding_dimension,
            )
            self._dim = int(dim_fn())
        return self._model

    @property
    def dim(self) -> int:
        self._load()
        assert self._dim is not None
        return self._dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        model = self._load()
        # normalize_embeddings=True makes inner-product == cosine, which IndexFlatIP
        # expects — load-bearing for retrieval correctness.
        # Source: https://www.sbert.net/docs/package_reference/SentenceTransformer.html#sentence_transformers.SentenceTransformer.encode — Verified 2026-06-27
        vecs = model.encode(
            list(texts),
            batch_size=256,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vecs.astype("float32")


class OpenAIEmbedder:
    """Hosted OpenAI embeddings via the same LiteLLM gateway used for completions.

    Opt-in (`MEDCODER_EMBEDDER=openai/text-embedding-3-large`). Requires
    `OPENAI_API_KEY` at build time. We L2-normalize manually because the OpenAI
    API does not guarantee unit vectors, and `IndexFlatIP` needs them.
    """

    # Known output dims so the dim-mismatch guard needs no network probe.
    _KNOWN_DIMS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(self, name: str, batch_size: int = 1000) -> None:
        self.name = name
        self._batch_size = batch_size
        self._dim: int | None = None

    def _model_key(self) -> str:
        """Strip an optional `openai/` provider prefix for the dim lookup."""
        return self.name.split("/", 1)[1] if "/" in self.name else self.name

    def _require_key(self) -> None:
        # Checked directly (not via have_api_key_for) because a bare
        # `text-embedding-*` name has no provider prefix for that helper to match.
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                f"Embedder {self.name!r} needs OPENAI_API_KEY at build time. Use the "
                "keyless MiniLM default (MEDCODER_EMBEDDER unset), or set the key."
            )

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = self._KNOWN_DIMS.get(self._model_key())
            if self._dim is None:  # unknown model → one tiny probe call
                self._dim = int(self.encode(["probe"]).shape[1])
        return self._dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        import litellm  # lazy import — only needed on the opt-in path

        self._require_key()
        items = list(texts)
        out: list[list[float]] = []
        for i in range(0, len(items), self._batch_size):
            batch = items[i : i + self._batch_size]
            # Response shape: {"data": [{"embedding": [...]}, ...]} (OpenAI format).
            # Source: https://docs.litellm.ai/docs/embedding/supported_providers/openai — Verified 2026-06-27
            resp = litellm.embedding(model=self.name, input=batch)
            out.extend(d["embedding"] for d in resp["data"])
        return _l2_normalize(np.array(out, dtype="float32"))


def make_embedder(name: str) -> Embedder:
    """Route an embedder name to its backend.

    Names starting with `openai/` or `text-embedding-` use the hosted OpenAI
    backend; everything else loads as a local sentence-transformers model (the
    MiniLM default, or a domain model such as SapBERT).
    """
    if name.startswith("openai/") or name.startswith("text-embedding-"):
        return OpenAIEmbedder(name)
    return SentenceTransformerEmbedder(name)
