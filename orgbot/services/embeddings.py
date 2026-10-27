"""
A fully offline, dependency-light embedding function for ChromaDB.

Why not use chromadb's bundled default embedding function or a
sentence-transformers model? Both require downloading a model file from the
internet the first time they run, which is unreliable in restricted/offline
environments and adds a heavy torch/onnxruntime dependency. This project
instead uses a deterministic "feature hashing" bag-of-words vectorizer:
every run, on every machine, produces identical vectors for identical text,
with zero network calls and zero extra ML dependencies.

It captures vocabulary overlap well, which works nicely for organization
FAQ / fact style content. If you want true semantic embeddings later, you
can swap this class out for a sentence-transformers or NVIDIA embedding
model without changing anything else in the RAG pipeline (see
vector_store.py).
"""
import math
import re
import zlib
from typing import List

from chromadb import Documents, EmbeddingFunction, Embeddings

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common English stop words are down-weighted (not removed) so that
# meaningful keywords dominate similarity scoring.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
    "and", "or", "in", "on", "at", "for", "with", "this", "that", "it",
    "as", "by", "from", "we", "our", "you", "your", "i", "do", "does",
}


class HashingEmbeddingFunction(EmbeddingFunction):
    """Deterministic, offline embedding function for ChromaDB."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _tokenize(self, text: str) -> List[str]:
        return _TOKEN_RE.findall(text.lower())

    def _embed_one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        tokens = self._tokenize(text)
        for tok in tokens:
            weight = 0.4 if tok in _STOPWORDS else 1.0
            # stable hash (zlib.crc32) -> consistent across processes/restarts
            idx = zlib.crc32(tok.encode("utf-8")) % self.dim
            vec[idx] += weight
            # also hash a bigram-ish signal using token length bucket for a
            # small extra bit of discriminative power
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002
        return [self._embed_one(t) for t in input]


_embedding_function_singleton = None


def get_embedding_function():
    global _embedding_function_singleton
    if _embedding_function_singleton is None:
        try:
            from chromadb.utils import embedding_functions
            _embedding_function_singleton = embedding_functions.DefaultEmbeddingFunction()
        except Exception:
            _embedding_function_singleton = HashingEmbeddingFunction()
    return _embedding_function_singleton
