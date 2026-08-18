"""
Simple word-based chunking with overlap, used for the vector (ChromaDB)
ingestion pipeline.
"""
from typing import List


def chunk_text(text: str, chunk_size: int = 180, overlap: int = 30) -> List[str]:
    """
    Split text into overlapping chunks of roughly `chunk_size` words.
    Overlap keeps context continuity between adjacent chunks.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    n = len(words)
    step = max(chunk_size - overlap, 1)

    while start < n:
        end = min(start + chunk_size, n)
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end == n:
            break
        start += step

    return chunks


def flatten_json(obj, prefix: str = "") -> List[str]:
    """
    Recursively flatten arbitrary JSON into human-readable "key: value"
    sentence fragments so it can be chunked/embedded the same way as text.
    Lists of dicts (e.g. [{"question":..,"answer":..}, ...]) are handled
    specially to keep each record together.
    """
    lines = []

    if isinstance(obj, dict):
        # Special-case common structured shapes to keep semantics readable.
        for key, value in obj.items():
            label = f"{prefix}{key}" if not prefix else f"{prefix} > {key}"
            if isinstance(value, (dict, list)):
                lines.extend(flatten_json(value, label))
            else:
                lines.append(f"{label}: {value}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                lines.extend(flatten_json(item, prefix))
                lines.append("")  # blank line separates records
            else:
                lines.append(f"{prefix}: {item}" if prefix else str(item))
    else:
        lines.append(f"{prefix}: {obj}" if prefix else str(obj))

    return lines


def json_to_text(obj) -> str:
    """Convert a parsed JSON object into a flat text blob for embedding."""
    return "\n".join([l for l in flatten_json(obj) if l is not None])
