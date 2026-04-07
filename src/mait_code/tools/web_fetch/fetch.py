"""HTTP fetching with SSRF protection, HTTPS upgrade, and size limits."""

import ipaddress
import logging
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_SIZE = 512 * 1024  # 512 KB
USER_AGENT = "mc-tool-web-fetch (mait-code)"


class FetchError(Exception):
    """Raised when a fetch fails."""


@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    charset: str
    body: bytes


def _parse_content_type(headers: Message) -> tuple[str, str]:
    """Extract content type and charset from response headers."""
    ct = headers.get_content_type() or "application/octet-stream"
    charset = headers.get_content_charset() or "utf-8"
    return ct, charset


def _validate_url(url: str) -> str:
    """Validate and normalise the URL. Returns the normalised URL."""
    if not url:
        raise FetchError("URL cannot be empty")

    # Upgrade http to https
    if url.startswith("http://"):
        url = "https://" + url[7:]
        logger.info("upgraded URL to HTTPS: %s", url)

    if not url.startswith("https://"):
        # Try adding scheme if missing
        if "://" not in url:
            url = "https://" + url
            logger.info("added HTTPS scheme: %s", url)
        else:
            raise FetchError(f"unsupported URL scheme: {url}")

    parsed = urlparse(url)
    if not parsed.hostname:
        raise FetchError(f"invalid URL (no hostname): {url}")

    return url


def _check_ssrf(hostname: str) -> None:
    """Block requests to private/loopback/link-local addresses."""
    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise FetchError(f"DNS resolution failed for {hostname}: {e}") from e

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise FetchError(
                f"blocked: {hostname} resolves to private address {ip_str} — "
                f"use --allow-private to override"
            )


def fetch_url(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_size: int = DEFAULT_MAX_SIZE,
    allow_private: bool = False,
) -> FetchResult:
    """Fetch a URL and return the response content.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.
        max_size: Maximum response body in bytes.
        allow_private: If True, allow fetching private/loopback IPs.

    Returns:
        FetchResult with the response data.

    Raises:
        FetchError: If the fetch fails for any reason.
    """
    url = _validate_url(url)
    parsed = urlparse(url)

    if not allow_private:
        _check_ssrf(parsed.hostname)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(max_size + 1)
            if len(body) > max_size:
                body = body[:max_size]
                logger.warning("response truncated at %d bytes", max_size)

            ct, charset = _parse_content_type(response.headers)
            final_url = response.url

            return FetchResult(
                url=final_url,
                status_code=response.status,
                content_type=ct,
                charset=charset,
                body=body,
            )
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"connection error: {e.reason}") from e
    except socket.timeout as e:
        raise FetchError(f"request timed out after {timeout}s") from e
    except OSError as e:
        raise FetchError(f"network error: {e}") from e
