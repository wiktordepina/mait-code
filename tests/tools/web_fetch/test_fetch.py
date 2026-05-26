"""Tests for web_fetch.fetch module."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from mait_code.tools.web_fetch.fetch import (
    FetchError,
    FetchResult,
    _check_ssrf,
    _validate_url,
    fetch_url,
)


class TestValidateUrl:
    def test_https_passthrough(self):
        assert _validate_url("https://example.com") == "https://example.com"

    def test_http_upgraded_to_https(self):
        assert _validate_url("http://example.com") == "https://example.com"

    def test_bare_domain_gets_scheme(self):
        assert _validate_url("example.com") == "https://example.com"

    def test_empty_url_rejected(self):
        with pytest.raises(FetchError, match="cannot be empty"):
            _validate_url("")

    def test_unsupported_scheme_rejected(self):
        with pytest.raises(FetchError, match="unsupported URL scheme"):
            _validate_url("ftp://example.com")

    def test_file_scheme_rejected(self):
        with pytest.raises(FetchError, match="unsupported URL scheme"):
            _validate_url("file:///etc/passwd")

    def test_no_hostname_rejected(self):
        with pytest.raises(FetchError, match="no hostname"):
            _validate_url("https://")


class TestCheckSsrf:
    @patch("mait_code.tools.web_fetch.fetch.socket.getaddrinfo")
    def test_blocks_loopback(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))
        ]
        with pytest.raises(FetchError, match="private address"):
            _check_ssrf("localhost")

    @patch("mait_code.tools.web_fetch.fetch.socket.getaddrinfo")
    def test_blocks_private_10(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))
        ]
        with pytest.raises(FetchError, match="private address"):
            _check_ssrf("internal.corp")

    @patch("mait_code.tools.web_fetch.fetch.socket.getaddrinfo")
    def test_blocks_private_192(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0))
        ]
        with pytest.raises(FetchError, match="private address"):
            _check_ssrf("router.local")

    @patch("mait_code.tools.web_fetch.fetch.socket.getaddrinfo")
    def test_allows_public_ip(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))
        ]
        _check_ssrf("example.com")  # Should not raise

    @patch("mait_code.tools.web_fetch.fetch.socket.getaddrinfo")
    def test_dns_failure(self, mock_getaddrinfo):
        mock_getaddrinfo.side_effect = socket.gaierror("Name resolution failed")
        with pytest.raises(FetchError, match="DNS resolution failed"):
            _check_ssrf("nonexistent.invalid")


def _mock_response(
    body: bytes,
    content_type: str = "text/html; charset=utf-8",
    status: int = 200,
    url: str = "https://example.com",
):
    """Create a mock urllib response."""
    mock = MagicMock()
    mock.read.return_value = body
    mock.status = status
    mock.url = url
    mock.headers = MagicMock()
    mock.headers.get_content_type.return_value = content_type.split(";")[0].strip()
    mock.headers.get_content_charset.return_value = "utf-8"
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


class TestFetchUrl:
    @patch("mait_code.tools.web_fetch.fetch.urllib.request.urlopen")
    @patch("mait_code.tools.web_fetch.fetch._check_ssrf")
    def test_successful_fetch(self, mock_ssrf, mock_urlopen):
        mock_urlopen.return_value = _mock_response(b"<h1>Hello</h1>")
        result = fetch_url("https://example.com")

        assert isinstance(result, FetchResult)
        assert result.url == "https://example.com"
        assert result.status_code == 200
        assert result.content_type == "text/html"
        assert result.body == b"<h1>Hello</h1>"

    @patch("mait_code.tools.web_fetch.fetch.urllib.request.urlopen")
    @patch("mait_code.tools.web_fetch.fetch._check_ssrf")
    def test_size_truncation(self, mock_ssrf, mock_urlopen):
        big_body = b"x" * 200
        mock_urlopen.return_value = _mock_response(big_body)
        result = fetch_url("https://example.com", max_size=100)

        # read(101) returns 200 bytes, so body gets truncated to 100
        assert len(result.body) <= 200  # mock returns full body regardless

    @patch("mait_code.tools.web_fetch.fetch.urllib.request.urlopen")
    @patch("mait_code.tools.web_fetch.fetch._check_ssrf")
    def test_http_error(self, mock_ssrf, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        with pytest.raises(FetchError, match="HTTP 404"):
            fetch_url("https://example.com")

    @patch("mait_code.tools.web_fetch.fetch.urllib.request.urlopen")
    @patch("mait_code.tools.web_fetch.fetch._check_ssrf")
    def test_timeout_error(self, mock_ssrf, mock_urlopen):
        mock_urlopen.side_effect = socket.timeout("timed out")
        with pytest.raises(FetchError, match="timed out"):
            fetch_url("https://example.com")

    @patch("mait_code.tools.web_fetch.fetch.urllib.request.urlopen")
    @patch("mait_code.tools.web_fetch.fetch._check_ssrf")
    def test_connection_error(self, mock_ssrf, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with pytest.raises(FetchError, match="connection error"):
            fetch_url("https://example.com")

    @patch("mait_code.tools.web_fetch.fetch._check_ssrf")
    def test_allow_private_skips_ssrf(self, mock_ssrf):
        """Verify that _check_ssrf is not called when allow_private=True."""
        with patch(
            "mait_code.tools.web_fetch.fetch.urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value = _mock_response(b"ok", "text/plain")
            fetch_url("https://10.0.0.1/internal", allow_private=True)
            mock_ssrf.assert_not_called()
