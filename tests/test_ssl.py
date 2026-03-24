"""Tests for SSL trust store injection."""

from unittest.mock import MagicMock, patch

from mait_code import ssl as ssl_mod
from mait_code.ssl import setup_ssl


class TestSetupSsl:
    """Tests for setup_ssl — OS trust store injection."""

    def setup_method(self):
        """Reset the module-level flag before each test."""
        ssl_mod._injected = False

    def test_injects_truststore(self):
        mock_truststore = MagicMock()
        with patch.dict("sys.modules", {"truststore": mock_truststore}):
            setup_ssl()
        mock_truststore.inject_into_ssl.assert_called_once()
        assert ssl_mod._injected is True

    def test_idempotent(self):
        mock_truststore = MagicMock()
        with patch.dict("sys.modules", {"truststore": mock_truststore}):
            setup_ssl()
            setup_ssl()
        mock_truststore.inject_into_ssl.assert_called_once()

    def test_graceful_when_not_installed(self):
        with patch.dict("sys.modules", {"truststore": None}):
            setup_ssl()  # Should not raise
        assert ssl_mod._injected is False

    def test_graceful_on_injection_failure(self):
        mock_truststore = MagicMock()
        mock_truststore.inject_into_ssl.side_effect = RuntimeError("injection failed")
        with patch.dict("sys.modules", {"truststore": mock_truststore}):
            setup_ssl()  # Should not raise
        assert ssl_mod._injected is False
