"""Tests for web_fetch.convert module."""

import json

from mait_code.tools.web_fetch.convert import convert_content


class TestHtmlConversion:
    def test_basic_html(self):
        html = b"<html><body><h1>Title</h1><p>Hello world</p></body></html>"
        result = convert_content(html, "text/html", "utf-8")
        assert "Title" in result
        assert "Hello world" in result

    def test_strips_script_tags(self):
        html = b"<html><body><script>alert('xss')</script><p>Content</p></body></html>"
        result = convert_content(html, "text/html", "utf-8")
        assert "alert" not in result
        assert "Content" in result

    def test_strips_style_tags(self):
        html = b"<html><body><style>.foo{color:red}</style><p>Content</p></body></html>"
        result = convert_content(html, "text/html", "utf-8")
        assert "color" not in result
        assert "Content" in result

    def test_strips_nav_footer_header(self):
        html = (
            b"<html><body>"
            b"<nav>Navigation</nav>"
            b"<header>Header</header>"
            b"<main><p>Main content</p></main>"
            b"<footer>Footer</footer>"
            b"</body></html>"
        )
        result = convert_content(html, "text/html", "utf-8")
        assert "Navigation" not in result
        assert "Header" not in result
        assert "Footer" not in result
        assert "Main content" in result

    def test_xhtml_content_type(self):
        html = b"<html><body><p>XHTML content</p></body></html>"
        result = convert_content(html, "application/xhtml+xml", "utf-8")
        assert "XHTML content" in result


class TestJsonConversion:
    def test_valid_json(self):
        data = {"key": "value", "number": 42}
        body = json.dumps(data).encode()
        result = convert_content(body, "application/json", "utf-8")
        assert '"key": "value"' in result
        assert '"number": 42' in result

    def test_invalid_json_returns_raw(self):
        body = b"not valid json {{"
        result = convert_content(body, "application/json", "utf-8")
        assert result == "not valid json {{"


class TestPlainText:
    def test_plain_text_passthrough(self):
        body = b"Just plain text content"
        result = convert_content(body, "text/plain", "utf-8")
        assert result == "Just plain text content"

    def test_csv_passthrough(self):
        body = b"name,age\nAlice,30\nBob,25"
        result = convert_content(body, "text/csv", "utf-8")
        assert "Alice,30" in result

    def test_xml_passthrough(self):
        body = b"<root><item>value</item></root>"
        result = convert_content(body, "application/xml", "utf-8")
        assert "<root>" in result


class TestBinaryContent:
    def test_binary_content_descriptive_message(self):
        body = b"\x89PNG\r\n" + b"\x00" * 1024
        result = convert_content(body, "image/png", "utf-8")
        assert "Binary content" in result
        assert "image/png" in result
        assert "KB" in result

    def test_pdf_content_descriptive_message(self):
        body = b"%PDF-1.4" + b"\x00" * 2048
        result = convert_content(body, "application/pdf", "utf-8")
        assert "Binary content" in result
        assert "application/pdf" in result


class TestTruncation:
    def test_truncation_at_limit(self):
        body = ("x" * 200).encode()
        result = convert_content(body, "text/plain", "utf-8", max_chars=100)
        assert len(result) > 100  # includes truncation message
        assert "[Content truncated at 100 characters]" in result

    def test_no_truncation_under_limit(self):
        body = b"short"
        result = convert_content(body, "text/plain", "utf-8", max_chars=100)
        assert "truncated" not in result
        assert result == "short"


class TestCharsetHandling:
    def test_utf8_default(self):
        body = "Hello world".encode("utf-8")
        result = convert_content(body, "text/plain", "utf-8")
        assert result == "Hello world"

    def test_latin1_charset(self):
        body = "caf\u00e9".encode("latin-1")
        result = convert_content(body, "text/plain", "latin-1")
        assert "caf" in result

    def test_invalid_charset_falls_back(self):
        body = b"Hello world"
        result = convert_content(body, "text/plain", "nonexistent-charset")
        assert "Hello" in result
