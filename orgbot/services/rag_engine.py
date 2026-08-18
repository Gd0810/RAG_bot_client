"""
The core RAG orchestration:

    1. Try the VECTOR method (ChromaDB semantic search over chunks).
    2. If the vector store returns nothing, or nothing relevant enough
       (best distance above VECTOR_DISTANCE_THRESHOLD), fall back to the
       PAGE-INDEX method (fast keyword search over the raw JSON page store).
    3. Whichever context was found gets handed to the NVIDIA LLM
       (with automatic primary -> fallback model retry) to produce the
       final natural-language answer, instructed to preserve any source
       URLs verbatim so they can be turned into clickable links.
"""
import logging
from django.conf import settings

from . import vector_store, page_index, llm_client
from .quick_responses import match_quick_response
from ..models import OrganizationProfile

logger = logging.getLogger(__name__)


def _build_system_prompt(profile) -> str:
    """Build a dynamic system prompt using real organization URLs from the DB."""
    org_name = getattr(profile, "name", "this organization") or "this organization"
    about_url = getattr(profile, "about_url", "") or ""
    contact_url = getattr(profile, "contact_url", "") or ""
    website_url = getattr(profile, "website_url", "") or ""

    # Build the fallback suggestion line using only available URLs
    fallback_links = []
    if about_url:
        fallback_links.append(f"visit our About page at {about_url}")
    if contact_url:
        fallback_links.append(f"contact us at {contact_url}")
    elif website_url:
        fallback_links.append(f"visit our website at {website_url}")

    if fallback_links:
        fallback_line = (
            "If the context does NOT contain enough information to answer, say so honestly and suggest the "
            "user " + " or ".join(fallback_links) + "."
        )
    else:
        fallback_line = (
            "If the context does NOT contain enough information to answer, say so honestly and suggest the "
            "user rephrase their question or contact the organization directly."
        )

    return f"""You are the official AI assistant embedded on {org_name}'s website.
Answer the user's question using ONLY the CONTEXT provided below, which was retrieved from the
organization's own knowledge base. Be friendly, concise, and helpful.

Rules:
- If the context contains a relevant answer, answer confidently in plain, natural language.
- If the context includes any URL(s) relevant to the answer (e.g. a contact page, a service page),
  include that exact URL in your answer, written out in full.
  Never invent or alter a URL - only use URLs that literally appear in the context.
- {fallback_line}
- Do not mention "context", "chunks", "documents", or your internal retrieval process to the user.
- Keep answers focused - a few sentences, or a short list when helpful.
"""


def _build_prompt(query: str, context_blocks: list) -> str:
    MAX_CONTEXT_CHARS = 25000
    MAX_BLOCK_CHARS = 12000

    normalized_blocks = []
    for block in context_blocks:
        if len(block) > MAX_BLOCK_CHARS:
            truncated = block[:MAX_BLOCK_CHARS].rstrip() + "\n\n[truncated]"
            normalized_blocks.append(truncated)
        else:
            normalized_blocks.append(block)

    context_text = "\n\n---\n\n".join(normalized_blocks) if normalized_blocks else "(no matching information found)"
    if len(context_text) > MAX_CONTEXT_CHARS:
        context_text = context_text[:MAX_CONTEXT_CHARS].rstrip() + "\n\n[truncated]"

    return (
        f"CONTEXT:\n{context_text}\n\n"
        f"USER QUESTION: {query}\n\n"
        "Write the final answer for the user now."
    )


def _try_vector_method(query: str):
    """Returns (context_blocks, sources, urls) or (None, None, None) if not confident enough."""
    try:
        results = vector_store.query(query, n_results=settings.VECTOR_TOP_K)
    except Exception as e:
        logger.warning("Vector store query failed, will fall back: %s", e)
        return None, None, None

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        return None, None, None

    best_distance = min(distances) if distances else None
    if best_distance is None or best_distance > settings.VECTOR_DISTANCE_THRESHOLD:
        return None, None, None

    context_blocks = []
    sources = []
    extracted_urls = []
    for doc, meta, dist in zip(documents, metadatas, distances):
        if dist > settings.VECTOR_DISTANCE_THRESHOLD:
            continue
        source_title = meta.get("source_title", "organization data")
        urls = meta.get("urls", "")
        if urls:
            extracted_urls.append(urls)
        block = f"[Source: {source_title}]\n{doc}"
        if urls:
            block += f"\n(Related links: {urls})"
        context_blocks.append(block)
        sources.append(source_title)

    if not context_blocks:
        return None, None, None

    return context_blocks, list(dict.fromkeys(sources)), extracted_urls


def _try_page_index_method(query: str):
    """Returns (context_blocks, sources, urls) or (None, None, None) if nothing matched."""
    matches = page_index.search(query, top_k=settings.PAGE_INDEX_TOP_K)
    if not matches:
        return None, None, None

    context_blocks = []
    sources = []
    extracted_urls = []
    for entry in matches:
        source_title = entry.get("source_title", "organization data")
        urls = entry.get("urls", [])
        if isinstance(urls, list):
            extracted_urls.extend(urls)
        elif urls:
            extracted_urls.append(str(urls))
        block = f"[Source: {source_title}]\n{entry.get('content', '')}"
        if urls:
            block += f"\n(Related links: {', '.join(urls)})"
        context_blocks.append(block)
        sources.append(source_title)

    return context_blocks, list(dict.fromkeys(sources)), extracted_urls


def answer_question(query: str) -> dict:
    """
    Main entry point. Returns:
        {
            "answer": str (raw text, not yet HTML-escaped/linkified),
            "method": "vector" | "page_index" | "quick_reply" | "none",
            "sources": [str, ...],
            "urls": [str, ...],
            "model_used": str | None,
        }
    """
    query = (query or "").strip()
    profile = OrganizationProfile.get_solo()
    if not query:
        return {
            "answer": "Please type a question so I can help you!",
            "method": "none",
            "sources": [],
            "urls": [],
            "model_used": None,
        }

    # Check for pre-defined quick responses (greetings, gratitude, small talk, etc.)
    quick_reply = match_quick_response(query)
    if quick_reply:
        return {
            "answer": quick_reply,
            "method": "quick_reply",
            "sources": [],
            "urls": [],
            "model_used": "Instant Reply",
        }

    method_used = "none"
    urls_found = []
    context_blocks, sources, urls_found = _try_vector_method(query)

    if context_blocks:
        method_used = "vector"
    else:
        context_blocks, sources, urls_found = _try_page_index_method(query)
        if context_blocks:
            method_used = "page_index"
        else:
            context_blocks = []
            sources = []
            urls_found = []

    prompt = _build_prompt(query, context_blocks)

    try:
        result = llm_client.generate_answer(_build_system_prompt(profile), prompt)
        return {
            "answer": result["answer"],
            "method": method_used,
            "sources": sources,
            "urls": urls_found or [],
            "model_used": result["model_used"],
        }
    except llm_client.LLMError as e:
        logger.error("LLM generation failed entirely: %s", e)
        return {
            "answer": (
                "Sorry, I'm having trouble reaching the AI service right now "
                "(please check the NVIDIA_API_KEY / model settings in your .env file). "
                f"Details: {e}"
            ),
            "method": method_used,
            "sources": sources,
            "urls": urls_found or [],
            "model_used": None,
        }
