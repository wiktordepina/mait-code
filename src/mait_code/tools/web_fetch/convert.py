"""Content conversion — HTML to markdown, JSON pretty-print, text passthrough."""

import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 100_000

# HTML tags that add noise without useful content
_STRIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript"}


def _html_to_markdown(html: str) -> str:
    """Convert HTML to markdown, stripping noise tags before conversion."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    md = markdownify(str(soup), heading_style="ATX", strip=["img"])

    # Collapse excessive blank lines
    lines = md.splitlines()
    collapsed = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                collapsed.append("")
        else:
            blank_count = 0
            collapsed.append(line)

    return "\n".join(collapsed).strip()


def _pretty_json(raw: str) -> str:
    """Pretty-print JSON; fall back to the raw text on parse error."""
    try:
        data = json.loads(raw)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        return raw


def convert_content(
    body: bytes,
    content_type: str,
    charset: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Convert fetched content to a text representation suitable for an LLM.

    Args:
        body: Raw response bytes.
        content_type: MIME type (e.g. "text/html").
        charset: Character encoding (e.g. "utf-8").
        max_chars: Maximum output length in characters.

    Returns:
        Converted text content, truncated if necessary.
    """
    # Binary content types — don't attempt to decode
    text_types = {
        "text/",
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/javascript",
        "application/x-javascript",
    }
    is_text = any(content_type.startswith(t) for t in text_types)

    if not is_text:
        size_kb = len(body) / 1024
        return (
            f"Binary content ({content_type}, {size_kb:.0f}KB). Cannot display inline."
        )

    # Decode to string
    try:
        text = body.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = body.decode("utf-8", errors="replace")

    # Route by content type
    if content_type in ("text/html", "application/xhtml+xml"):
        result = _html_to_markdown(text)
    elif content_type == "application/json":
        result = _pretty_json(text)
    else:
        # text/plain, text/csv, text/xml, application/xml, etc.
        result = text

    # Truncate if needed
    if len(result) > max_chars:
        result = (
            result[:max_chars] + f"\n\n[Content truncated at {max_chars} characters]"
        )

    return result
