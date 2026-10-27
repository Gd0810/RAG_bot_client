"""
RAG method #2: "Page Indexing".

Instead of embeddings, source documents are stored verbatim (chunked into
larger "pages") in a single plain JSON file. Looking things up is just fast
keyword/text-overlap scoring over that JSON - no vector math, no embedding
model call - which is why it's noticeably quicker than the vector method.
It is used as the fallback whenever the vector store has no good match.
"""
import json
import re
import threading
from pathlib import Path
from typing import List, Dict, Any

from django.conf import settings

_lock = threading.Lock()
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
    "and", "or", "in", "on", "at", "for", "with", "this", "that", "it",
    "as", "by", "from", "we", "our", "you", "your", "i", "do", "does",
    "what", "who", "where", "when", "how", "please", "tell", "me", "about",
}


def _ensure_dir():
    settings.PAGE_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if not Path(settings.PAGE_INDEX_FILE).exists():
        Path(settings.PAGE_INDEX_FILE).write_text("[]", encoding="utf-8")


def load_index() -> List[Dict[str, Any]]:
    _ensure_dir()
    try:
        with open(settings.PAGE_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_index(entries: List[Dict[str, Any]]):
    _ensure_dir()
    with _lock:
        with open(settings.PAGE_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)


URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")


def add_pages(pages: List[str], source_title: str, doc_id: int, urls: List[str] = None):
    """Append page-level entries for a document to the shared page index."""
    entries = load_index()
    next_id = (max((e.get("id", 0) for e in entries), default=0)) + 1
    for i, page in enumerate(pages):
        page_urls = list(dict.fromkeys(URL_RE.findall(page)))
        entries.append({
            "id": next_id,
            "doc_id": doc_id,
            "source_title": source_title,
            "content": page,
            "urls": page_urls[:5],
        })
        next_id += 1
    save_index(entries)
    return len(pages)


def delete_by_doc_id(doc_id: int):
    entries = load_index()
    entries = [e for e in entries if e.get("doc_id") != doc_id]
    save_index(entries)


def _tokenize(text: str) -> set:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def _score(query_tokens: set, entry_text: str) -> float:
    entry_tokens = _tokenize(entry_text)
    if not entry_tokens or not query_tokens:
        return 0.0
    overlap = query_tokens & entry_tokens
    if not overlap:
        return 0.0
    # weight by overlap ratio relative to the query (recall-ish) and a
    # small bonus for exact substring phrase matches
    score = len(overlap) / len(query_tokens)
    return score


def search(query_text: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Return the top_k most relevant page-index entries for a query."""
    entries = load_index()
    if not entries:
        return []

    query_tokens = _tokenize(query_text)
    scored = []
    for entry in entries:
        score = _score(query_tokens, entry.get("content", ""))
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for score, entry in scored[:top_k]]


def total_entries() -> int:
    return len(load_index())
