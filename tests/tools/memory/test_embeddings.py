"""Tests for the embeddings module."""

import struct
from unittest.mock import MagicMock, patch

from mait_code.tools.memory.embeddings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    serialize_f32,
)


class TestSerializeF32:
    def test_round_trip(self):
        """Serialized bytes should have correct length."""
        vec = [0.1] * 768
        data = serialize_f32(vec)
        assert len(data) == 768 * 4  # 4 bytes per float32

    def test_empty_vector(self):
        assert serialize_f32([]) == b""

    def test_values_preserved(self):
        vec = [1.0, 2.0, 3.0]
        data = serialize_f32(vec)
        unpacked = struct.unpack("3f", data)
        assert list(unpacked) == vec


class TestConstants:
    def test_default_model_name(self):
        assert "nomic" in EMBEDDING_MODEL

    def test_default_dimension(self):
        assert EMBEDDING_DIM == 768

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"})
    def test_bedrock_default_dimension(self):
        from mait_code.tools.memory.embeddings import _get_embedding_dim

        assert _get_embedding_dim() == 1024

    @patch.dict(
        "os.environ",
        {
            "MAIT_CODE_EMBEDDING_PROVIDER": "bedrock",
            "MAIT_CODE_BEDROCK_MODEL_ID": "amazon.titan-embed-text-v1",
        },
    )
    def test_bedrock_custom_model_dimension(self):
        from mait_code.tools.memory.embeddings import _get_embedding_dim

        assert _get_embedding_dim() == 1536

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"})
    def test_bedrock_model_name(self):
        from mait_code.tools.memory.embeddings import _get_embedding_model

        assert "titan" in _get_embedding_model()


class TestGracefulDegradation:
    def test_embed_text_returns_none_when_unavailable(self):
        """embed_text should return None if provider fails to load."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = False

        try:
            with patch.dict("sys.modules", {"fastembed": None}):
                mod._provider_failed = False  # Reset so it tries again
                result = mod.embed_text("test text")
                assert result is None
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_texts_returns_none_when_unavailable(self):
        """embed_texts should return None if provider is unavailable."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = True

        try:
            result = mod.embed_texts(["test"])
            assert result is None
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_is_available_false_when_failed(self):
        """is_available should return False if provider failed."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = True

        try:
            assert mod.is_available() is False
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed


class TestEmbedWithMockProvider:
    """Test embed functions with a mocked provider."""

    def _make_mock_provider(self, dim=768):
        provider = MagicMock()
        provider.embed.return_value = [[0.0] * dim]
        provider.dimension = dim
        provider.model_name = "mock-model"
        return provider

    def test_embed_text_prepends_prefix_for_local(self):
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = self._make_mock_provider()
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}):
                result = mod.embed_text("hello world", prefix="search_query")
                assert result is not None
                assert len(result) == 768
                mock.embed.assert_called_once_with(["search_query: hello world"])
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_text_default_prefix(self):
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = self._make_mock_provider()
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}):
                mod.embed_text("hello world")
                mock.embed.assert_called_once_with(
                    ["search_document: hello world"]
                )
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_text_no_prefix_for_bedrock(self):
        """Bedrock provider should NOT prepend prefix."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = self._make_mock_provider(dim=1024)
        mock.embed.return_value = [[0.0] * 1024]
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict(
                "os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}
            ):
                result = mod.embed_text("hello world", prefix="search_query")
                assert result is not None
                assert len(result) == 1024
                mock.embed.assert_called_once_with(["hello world"])
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_texts_batch(self):
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = self._make_mock_provider()
        mock.embed.return_value = [[0.0] * 768, [1.0] * 768]
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}):
                result = mod.embed_texts(["a", "b"], prefix="search_document")
                assert result is not None
                assert len(result) == 2
                assert len(result[0]) == 768
                mock.embed.assert_called_once_with(
                    ["search_document: a", "search_document: b"]
                )
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_texts_no_prefix_for_bedrock(self):
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = self._make_mock_provider(dim=1024)
        mock.embed.return_value = [[0.0] * 1024, [1.0] * 1024]
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict(
                "os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}
            ):
                result = mod.embed_texts(["a", "b"])
                assert result is not None
                mock.embed.assert_called_once_with(["a", "b"])
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed


class TestBedrockProvider:
    """Test BedrockProvider graceful degradation."""

    def test_bedrock_missing_boto3(self):
        """BedrockProvider should fail gracefully if boto3 is missing."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = False

        try:
            with patch.dict(
                "os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}
            ):
                with patch.dict("sys.modules", {"boto3": None}):
                    result = mod.get_provider()
                    assert result is None
                    assert mod._provider_failed is True
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_bedrock_invoke_model_mock(self):
        """BedrockProvider.embed should call invoke_model with correct payload."""
        import json

        from mait_code.tools.memory.embeddings import BedrockProvider

        # Create a fake boto3 module since it may not be installed
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        # Mock invoke_model response for Titan
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"embedding": [0.1] * 1024}
        ).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.dict(
            "os.environ",
            {
                "MAIT_CODE_BEDROCK_MODEL_ID": "amazon.titan-embed-text-v2:0",
                "MAIT_CODE_BEDROCK_REGION": "eu-west-2",
            },
        ):
            with patch.dict("sys.modules", {"boto3": mock_boto3}):
                with patch("mait_code.ssl.setup_ssl"):
                    provider = BedrockProvider()
                    result = provider.embed(["test text"])

                    assert len(result) == 1
                    assert len(result[0]) == 1024
                    mock_client.invoke_model.assert_called_once()
                    call_kwargs = mock_client.invoke_model.call_args
                    body = json.loads(call_kwargs.kwargs["body"])
                    assert body["inputText"] == "test text"
                    assert body["dimensions"] == 1024


class TestDimensionCheck:
    """Test check_dimension_match function."""

    def test_empty_table_matching_declaration(self):
        """Empty vec table with matching declared dimension."""
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()

        def _execute(sql, *args):
            result = MagicMock()
            if "sqlite_master" in sql:
                result.fetchone.return_value = (
                    "CREATE VIRTUAL TABLE memory_vec "
                    "USING vec0(embedding float[768] distance_metric=cosine)",
                )
            else:
                result.fetchone.return_value = None
            return result

        conn.execute = _execute

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim == 768

    def test_empty_table_mismatched_declaration(self):
        """Empty vec table with mismatched declared dimension."""
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()

        def _execute(sql, *args):
            result = MagicMock()
            if "sqlite_master" in sql:
                result.fetchone.return_value = (
                    "CREATE VIRTUAL TABLE memory_vec "
                    "USING vec0(embedding float[1024] distance_metric=cosine)",
                )
            else:
                result.fetchone.return_value = None
            return result

        conn.execute = _execute

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is False
        assert table_dim == 1024
        assert expected == 768

    def test_matching_dimension(self):
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        # 768 floats * 4 bytes = 3072 bytes
        conn.execute.return_value.fetchone.return_value = (b"\x00" * (768 * 4),)

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim == 768

    def test_mismatched_dimension(self):
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        # 1024 floats * 4 bytes = 4096 bytes — mismatch with default 768
        conn.execute.return_value.fetchone.return_value = (b"\x00" * (1024 * 4),)

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is False
        assert table_dim == 1024
        assert expected == 768

    def test_exception_returns_match(self):
        """If the table doesn't exist, assume it matches."""
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        conn.execute.side_effect = Exception("no such table")

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim is None
