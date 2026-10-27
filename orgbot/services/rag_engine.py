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

    if profile.dashboard_mode:
        fallback_rule = (
            "- If the context does NOT contain enough information to answer the user's question, "
            "your response MUST begin with '[NO_DB_INFO]' so the system can prompt the user to "
            "route their inquiry to the relevant department."
        )
    elif fallback_links:
        fallback_rule = (
            "- If the context does NOT contain enough information to answer, say so honestly and suggest the "
            "user " + " or ".join(fallback_links) + "."
        )
    else:
        fallback_rule = (
            "- If the context does NOT contain enough information to answer, say so honestly and suggest the "
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
{fallback_rule}
- Do not mention "context", "chunks", "documents", or your internal retrieval process to the user.
- Keep answers focused - a few sentences, or a short list when helpful.
"""


def _build_prompt(query: str, context_blocks: list) -> str:
    MAX_CONTEXT_CHARS = 3500
    MAX_BLOCK_CHARS = 1600

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
        raw_urls = meta.get("urls", "")
        if raw_urls:
            for u in raw_urls.split(", "):
                u_clean = u.strip()
                if u_clean and u_clean not in extracted_urls:
                    extracted_urls.append(u_clean)
        block = f"[Source: {source_title}]\n{doc}"
        if raw_urls:
            block += f"\n(Related links: {raw_urls})"
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
    sources = []
    urls_found = []
    context_blocks = []

    # 1. Semantic vector search (dense embeddings)
    vector_blocks, vector_sources, vector_urls = _try_vector_method(query)
    if vector_blocks:
        context_blocks.extend(vector_blocks)
        sources.extend(vector_sources or [])
        urls_found.extend(vector_urls or [])
        method_used = "vector"

    # 2. Keyword page index search (sparse exact matching)
    page_blocks, page_sources, page_urls = _try_page_index_method(query)
    if page_blocks:
        for pb in page_blocks:
            snippet = pb[:80]
            if not any(snippet in cb for cb in context_blocks):
                context_blocks.append(pb)
        sources.extend(page_sources or [])
        urls_found.extend(page_urls or [])
        if method_used == "none":
            method_used = "page_index"
        else:
            method_used = "hybrid"

    sources = list(dict.fromkeys(sources))
    urls_found = list(dict.fromkeys(urls_found))

    # If dashboard_mode is enabled and no relevant context was found in DB
    if profile.dashboard_mode and method_used == "none":
        return {
            "answer": (
                "The relevant data you asked about is not in my Database. "
                "Please share your details in the form below so that the particular "
                "department admin can respond shortly via your email."
            ),
            "method": "none",
            "sources": [],
            "urls": [],
            "model_used": "Department Router",
            "show_visitor_form": True,
            "query": query,
        }

    prompt = _build_prompt(query, context_blocks)

    try:
        result = llm_client.generate_answer(_build_system_prompt(profile), prompt)
        raw_answer = result["answer"]

        show_visitor_form = False
        final_answer = raw_answer

        if profile.dashboard_mode:
            answer_lower = raw_answer.lower()
            missing_indicators = [
                "[no_db_info]",
                "not enough information in my database",
                "not in my database",
                "not enough information to answer",
                "do not have enough information to answer",
                "don't have enough information to answer",
                "not have sufficient information to answer",
                "i do not have information to answer",
                "i don't have information to answer",
                "not available in the provided context",
                "no information found in the database",
                "no information in the database",
                "context does not contain",
                "context doesn't contain",
                "not related to the provided context",
                "doesn't seem to be related",
                "does not seem to be related",
                "cannot answer based on the provided context",
                "unable to answer based on the provided context",
            ]
            if any(indicator in answer_lower for indicator in missing_indicators):
                show_visitor_form = True
                final_answer = (
                    "The relevant data you asked about is not in my Database. "
                    "Please share your details in the form below so that the particular "
                    "department admin can respond shortly via your email."
                )

        return {
            "answer": final_answer,
            "method": method_used,
            "sources": sources,
            "urls": urls_found or [],
            "model_used": result["model_used"],
            "show_visitor_form": show_visitor_form,
            "query": query,
        }
    except llm_client.LLMError as e:
        logger.error("LLM generation failed entirely: %s", e)
        show_visitor_form = profile.dashboard_mode
        fallback_msg = (
            "The relevant data you asked about is not in my Database. "
            "Please share your details in the form below so that the particular "
            "department admin can respond shortly via your email."
            if profile.dashboard_mode
            else (
                "Sorry, I'm having trouble reaching the AI service right now "
                "(please check the NVIDIA_API_KEY / model settings in your .env file). "
                f"Details: {e}"
            )
        )
        return {
            "answer": fallback_msg,
            "method": method_used,
            "sources": sources,
            "urls": urls_found or [],
            "model_used": None,
            "show_visitor_form": show_visitor_form,
            "query": query,
        }


