"""Web-fetch tool — fetch URLs and convert HTML to Markdown.

A thin wrapper that fetches a URL, identifies the content type, and either
passes it through (text/plain, application/json) or converts HTML to
Markdown via markdownify. The CLI (``main``) is the user-facing surface;
``fetch_url`` and ``convert_content`` are the reusable library pieces.
"""

from mait_code.tools.web_fetch.cli import main
from mait_code.tools.web_fetch.convert import convert_content
from mait_code.tools.web_fetch.fetch import FetchError, FetchResult, fetch_url

__all__ = [
    "FetchError",
    "FetchResult",
    "convert_content",
    "fetch_url",
    "main",
]
