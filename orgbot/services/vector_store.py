"""
Thin wrapper around a persistent ChromaDB collection - this is RAG method #1
(embedding-based semantic search).
"""
import uuid
from typing import List, Dict, Any

import chromadb
from django.conf import settings

from .embeddings import get_embedding_function

_client = None
_collection = None


def get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    return _client


def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION_NAME,
            embedding_function=get_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def reset_collection():
    global _collection
    client = get_client()
    try:
        client.delete_collection(settings.CHROMA_COLLECTION_NAME)
    except Exception:
        pass
    _collection = None
    return get_collection()


def _get_max_batch_size() -> int:
    """
    Chroma's local backend caps how many records can go into a single
    .add() call (this is a SQLite variable-count limit under the hood, not
    something configurable). We ask the client for the real number rather
    than hardcoding it, since it can vary by chromadb version/backend.
    """
    try:
        client = get_client()
        return max(int(client.get_max_batch_size()), 1)
    except Exception:
        return 4000  # conservative fallback if the API isn't available


import re

URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")


def _extract_chunk_urls(text: str) -> List[str]:
    return list(dict.fromkeys(URL_RE.findall(text)))


def add_chunks(chunks: List[str], source_title: str, doc_id: int, urls: List[str] = None):
    """
    Embed and store a list of text chunks with metadata linking back to
    source. Large documents can produce thousands of chunks, which exceeds
    Chroma's single-call batch limit - so we split into safe-sized batches
    and add them one batch at a time.
    """
    if not chunks:
        return 0
    collection = get_collection()
    max_batch = _get_max_batch_size()

    total_added = 0
    for start in range(0, len(chunks), max_batch):
        batch = chunks[start:start + max_batch]
        ids = [f"doc{doc_id}-{uuid.uuid4().hex[:10]}" for _ in batch]
        metadatas = []
        for chunk in batch:
            chunk_urls = _extract_chunk_urls(chunk)
            metadatas.append({
                "source_title": source_title,
                "doc_id": doc_id,
                "urls": ", ".join(chunk_urls[:4]),
            })
        collection.add(documents=batch, ids=ids, metadatas=metadatas)
        total_added += len(batch)

    return total_added


def delete_by_doc_id(doc_id: int):
    collection = get_collection()
    try:
        collection.delete(where={"doc_id": doc_id})
    except Exception:
        pass


def query(query_text: str, n_results: int = 4) -> Dict[str, Any]:
    """
    Run a semantic search. Returns dict with documents, metadatas, distances
    (lower distance = more similar, since we use cosine space).
    Returns empty structure if the collection has no data yet.
    """
    collection = get_collection()
    if collection.count() == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    n_results = min(n_results, collection.count())
    results = collection.query(
        query_texts=[query_text],
        n_results=max(n_results, 1),
    )
    return results


def collection_count() -> int:
    return get_collection().count()