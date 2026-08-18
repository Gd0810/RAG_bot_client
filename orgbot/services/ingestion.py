"""
Takes an uploaded KnowledgeDocument (.txt or .json) and populates BOTH
retrieval backends:
  1. ChromaDB (chunked + embedded)          -> vector_store.py
  2. page_index.json (page-level, verbatim) -> page_index.py
"""
import json
import re

from . import chunking, vector_store, page_index

URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")


def extract_urls(text: str):
    return list(dict.fromkeys(URL_RE.findall(text)))  # de-dup, preserve order


def process_document(document) -> int:
    """
    Reads document.source_file, builds vector chunks + page-index entries.
    Returns the number of vector chunks created. Raises on failure so the
    admin can surface the error.
    """
    document.source_file.open("rb")
    raw_bytes = document.source_file.read()
    document.source_file.close()
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    if document.file_type == "json":
        parsed = json.loads(raw_text)
        full_text = chunking.json_to_text(parsed)
    else:
        full_text = raw_text

    urls = extract_urls(full_text)

    # ---- 1) Vector method: smaller overlapping chunks for precise recall ----
    vector_chunks = chunking.chunk_text(full_text, chunk_size=180, overlap=30)
    n_chunks = vector_store.add_chunks(
        chunks=vector_chunks,
        source_title=document.title,
        doc_id=document.id,
        urls=urls,
    )

    # ---- 2) Page-index method: larger "pages" for fast, low-overhead lookup ----
    page_chunks = chunking.chunk_text(full_text, chunk_size=500, overlap=0)
    if not page_chunks:
        page_chunks = [full_text]
    page_index.add_pages(
        pages=page_chunks,
        source_title=document.title,
        doc_id=document.id,
        urls=urls,
    )

    return n_chunks


def remove_document(document):
    vector_store.delete_by_doc_id(document.id)
    page_index.delete_by_doc_id(document.id)
