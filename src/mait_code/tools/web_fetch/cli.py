"""CLI tool for fetching web content — returns markdown-converted HTML or raw text."""

import argparse
import logging
import sys

from mait_code.logging import log_invocation, setup_logging
from mait_code.ssl import setup_ssl

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_SIZE = 512 * 1024
DEFAULT_MAX_CHARS = 100_000


@log_invocation(name="mc-tool-web-fetch")
def main():
    setup_logging()
    setup_ssl()

    parser = argparse.ArgumentParser(
        prog="mc-tool-web-fetch",
        description="Fetch a URL and return content as markdown or text",
    )
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE,
        help=f"Maximum response size in bytes (default: {DEFAULT_MAX_SIZE})",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"Maximum output characters (default: {DEFAULT_MAX_CHARS})",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Output raw content without markdown conversion",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Allow fetching private/loopback IP addresses",
    )

    args = parser.parse_args()

    from mait_code.tools.web_fetch.convert import convert_content
    from mait_code.tools.web_fetch.fetch import FetchError, fetch_url

    try:
        result = fetch_url(
            args.url,
            timeout=args.timeout,
            max_size=args.max_size,
            allow_private=args.allow_private,
        )
    except FetchError as e:
        logger.error("fetch failed: %s", e)
        print(f"Error fetching {args.url}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.raw:
        charset = result.charset or "utf-8"
        try:
            text = result.body.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = result.body.decode("utf-8", errors="replace")
        print(text[: args.max_chars])
    else:
        output = convert_content(
            result.body,
            result.content_type,
            result.charset,
            max_chars=args.max_chars,
        )
        print(f"URL: {result.url}")
        print(f"Content-Type: {result.content_type}")
        print("---")
        print(output)
