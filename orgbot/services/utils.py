"""
Helper to safely render LLM answers as HTML and format Related Links pills.

Key logic:
  - URLs are extracted ONLY from what the LLM actually wrote in the answer.
  - extra_urls from metadata are used ONLY as a scored pool to find closely
    related links via path-keyword overlap with the answer text.
  - A maximum of 4 related link pills are shown to avoid noise.
"""
import html
import re
from urllib.parse import urlparse

URL_RE = re.compile(r"(https?://[^\s\"'<>\)\]]+)", re.IGNORECASE)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# Stop words to ignore when scoring URL relevance
_STOP_WORDS = {
    "the", "a", "an", "is", "it", "in", "of", "and", "or", "to", "for",
    "on", "with", "by", "at", "this", "that", "are", "was", "be", "as",
    "i", "you", "we", "they", "he", "she", "www", "http", "https", "com",
    "ac", "in", "org", "net", "edu", "html", "php", "aspx", "pdf",
}

MAX_RELATED_LINKS = 4


def _path_tokens(url: str) -> set:
    """Return meaningful lowercase tokens from a URL path."""
    try:
        path = urlparse(url).path.strip("/")
        raw = re.split(r"[-_/]+", path.lower())
        return {t for t in raw if t and t not in _STOP_WORDS and len(t) > 1}
    except Exception:
        return set()


def _answer_tokens(text: str) -> set:
    """Return meaningful lowercase words from a block of plain text."""
    words = re.findall(r"[a-z]{2,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def get_url_label(url: str) -> str:
    """
    Extracts a clean, human-friendly button label from a URL.
    Example: 'https://example.com/about-us/' -> 'About Us'
    """
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            return "Website"
        parts = [p for p in path.split("/") if p]
        if not parts:
            return "Website"
        last = parts[-1]
        last = re.sub(r"\.(html|php|aspx|json|pdf)$", "", last, flags=re.IGNORECASE)
        cleaned = re.sub(r"[-_]+", " ", last).strip()
        if not cleaned:
            return "Website"
        words = [w.capitalize() for w in cleaned.split()]
        label = " ".join(words)
        return label if len(label) <= 25 else label[:22] + "..."
    except Exception:
        return "Visit Link"


def _score_url(url: str, answer_tokens: set) -> int:
    """
    Score a candidate URL by how many of its path tokens appear in the
    answer text tokens. Higher = more relevant.
    """
    url_tokens = _path_tokens(url)
    if not url_tokens:
        return 0
    return len(url_tokens & answer_tokens)


def render_answer_html(
    text: str,
    extra_urls: list | None = None,
    show_visitor_form: bool = False,
    query: str = "",
) -> str:
    escaped = html.escape(text)
    cited_urls = []   # URLs the LLM explicitly wrote in its answer text

    def _link(match):
        raw_url = match.group(1)
        trailing = ""
        while raw_url and raw_url[-1] in ".,;:!?)":
            trailing = raw_url[-1] + trailing
            raw_url = raw_url[:-1]
        if raw_url and raw_url not in cited_urls:
            cited_urls.append(raw_url)
        return (
            f'<a href="{raw_url}" target="_blank" rel="noopener noreferrer" '
            f'class="chat-link">{raw_url}</a>{trailing}'
        )

    linked = URL_RE.sub(_link, escaped)
    bolded = BOLD_RE.sub(r"<strong>\1</strong>", linked)
    with_breaks = bolded.replace("\n", "<br>")

    # If visitor form is required, append form directly and suppress extra URLs
    if show_visitor_form:
        escaped_query = html.escape(query)
        form_html = (
            f'<div class="visitor-request-card" style="margin-top: 14px; padding: 16px; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); text-align: left;">'
            f'<div style="font-weight: 700; font-size: 14px; margin-bottom: 6px; color: #0f172a; display: flex; align-items: center; gap: 6px;">'
            f'<span>📋</span> Web Visitor Request Form'
            f'</div>'
            f'<p style="font-size: 13px; color: #475569; margin-bottom: 12px; line-height: 1.4;">'
            f'Please submit your details below. Our system will automatically categorize your question and route it to the respective department admin for an email response.'
            f'</p>'
            f'<form class="visitor-req-form" data-query="{escaped_query}" style="display: flex; flex-direction: column; gap: 10px;">'
            f'<div>'
            f'<label style="display: block; font-size: 12px; font-weight: 600; color: #334155; margin-bottom: 4px;">Your Name</label>'
            f'<input type="text" name="name" placeholder="Enter your name (e.g. Giri)" required style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 13px; background: #ffffff; color: #0f172a; box-sizing: border-box;" />'
            f'</div>'
            f'<div>'
            f'<label style="display: block; font-size: 12px; font-weight: 600; color: #334155; margin-bottom: 4px;">Your Email</label>'
            f'<input type="email" name="email" placeholder="Enter your email (e.g. giri123@gmail.com)" required style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 13px; background: #ffffff; color: #0f172a; box-sizing: border-box;" />'
            f'</div>'
            f'<button type="submit" style="padding: 9px 16px; background: #2563eb; color: #ffffff; border: none; border-radius: 6px; font-weight: 600; font-size: 13px; cursor: pointer; align-self: flex-start;">'
            f'Submit Request'
            f'</button>'
            f'</form>'
            f'<div class="visitor-req-status" style="display: none; margin-top: 10px; padding: 10px; background: #dcfce7; border: 1px solid #bbf7d0; border-radius: 6px; font-weight: 600; font-size: 13px; color: #15803d;"></div>'
            f'</div>'
        )
        return with_breaks + form_html

    # --- Determine the best related links to show ---
    answer_tokens = _answer_tokens(text)
    related_urls = []

    # 1. URLs already cited in the answer text always appear first (they're directly relevant)
    for u in cited_urls:
        if u not in related_urls:
            related_urls.append(u)

    # 2. Score extra_urls from metadata against answer content, pick top matches only
    if extra_urls:
        candidates = []
        for u in extra_urls:
            if not u:
                continue
            parts = re.split(r"[,\s]+", str(u).strip())
            for single_u in parts:
                single_u = single_u.strip().rstrip(".,;:!?)")
                if not single_u.startswith("http"):
                    continue
                if single_u in related_urls:
                    continue
                score = _score_url(single_u, answer_tokens)
                if score > 0:
                    candidates.append((score, single_u))

        candidates.sort(key=lambda x: -x[0])
        remaining_slots = MAX_RELATED_LINKS - len(related_urls)
        for score, u in candidates[:remaining_slots]:
            related_urls.append(u)

    # --- Deduplicate (preserve order) and cap ---
    seen = set()
    final_urls = []
    for u in related_urls:
        if u not in seen:
            seen.add(u)
            final_urls.append(u)
    final_urls = final_urls[:MAX_RELATED_LINKS]

    # --- Render RELATED LINKS section ---
    if final_urls:
        pills_html = []
        for url in final_urls:
            label = get_url_label(url)
            pill = (
                f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="related-link-pill">'
                f'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" '
                f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
                f'<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>'
                f'<polyline points="15 3 21 3 21 9"></polyline>'
                f'<line x1="10" y1="14" x2="21" y2="3"></line>'
                f'</svg>'
                f'<span>{html.escape(label)}</span>'
                f'</a>'
            )
            pills_html.append(pill)

        related_section = (
            f'<div class="related-links-block">'
            f'<div class="related-links-label">RELATED LINKS</div>'
            f'<div class="related-links-pills">{"".join(pills_html)}</div>'
            f'</div>'
        )
        with_breaks += related_section

    return with_breaks

