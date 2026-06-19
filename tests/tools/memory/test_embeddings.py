"""Tests for the embeddings module."""

import os
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

from mait_code.tools.memory.embeddings import serialize_f32


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
    """Module-level constants are computed at import time from env vars.

    The root ``_isolate_mait_settings`` fixture clears every ``MAIT_CODE_*`` var,
    so under test the constants resolve to the ``local`` defaults regardless of
    the developer's shell. The module is collected before that fixture runs, so
    reload it here to recompute the constants against the isolated environment.
    """

    def test_default_model_name(self):
        import importlib

        import mait_code.tools.memory.embeddings as emb

        emb = importlib.reload(emb)
        assert "nomic" in emb.EMBEDDING_MODEL

    def test_default_dimension(self):
        import importlib

        import mait_code.tools.memory.embeddings as emb

        emb = importlib.reload(emb)
        assert emb.EMBEDDING_DIM == 768

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_local_default_dimension(self):
        from mait_code.tools.memory.embeddings import _get_embedding_dim

        assert _get_embedding_dim() == 768

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_local_model_name(self):
        from mait_code.tools.memory.embeddings import _get_embedding_model

        assert "nomic" in _get_embedding_model()

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
    @staticmethod
    def _provider_dep_module() -> str:
        """Return the dependency module name for the active provider."""
        provider = os.environ.get("MAIT_CODE_EMBEDDING_PROVIDER", "local").lower()
        return "boto3" if provider == "bedrock" else "fastembed"

    def test_embed_text_returns_none_when_unavailable(self):
        """embed_text should return None if provider fails to load."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = False

        dep = self._provider_dep_module()
        try:
            with patch.dict("sys.modules", {dep: None}):
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

    def test_get_provider_returns_local_on_success(self):
        """A successful local load is cached and returned as the singleton."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = False

        fake_fastembed = MagicMock()
        fake_fastembed.TextEmbedding.return_value = MagicMock()
        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}):
                with patch.dict("sys.modules", {"fastembed": fake_fastembed}):
                    provider = mod.get_provider()
                    assert provider is not None
                    # Singleton: a second call returns the same instance.
                    assert mod.get_provider() is provider
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_get_provider_generic_failure_returns_none(self):
        """A non-ImportError during init degrades to None (not propagated)."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = False

        # boto3 imports fine but client construction blows up — generic Exception.
        mock_boto3 = MagicMock()
        mock_boto3.client.side_effect = RuntimeError("no credentials")
        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}):
                with patch.dict("sys.modules", {"boto3": mock_boto3}):
                    with patch("mait_code.ssl.setup_ssl"):
                        assert mod.get_provider() is None
                        assert mod._provider_failed is True
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_text_returns_none_on_provider_error(self):
        """A provider that raises mid-embed degrades embed_text to None."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = MagicMock()
        mock.embed.side_effect = RuntimeError("boom")
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}):
                assert mod.embed_text("anything") is None
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed

    def test_embed_texts_returns_none_on_provider_error(self):
        """A provider that raises mid-embed degrades embed_texts to None."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mock = MagicMock()
        mock.embed.side_effect = RuntimeError("boom")
        mod._provider = mock
        mod._provider_failed = False

        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}):
                assert mod.embed_texts(["a", "b"]) is None
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
                mock.embed.assert_called_once_with(["search_document: hello world"])
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
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}):
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
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}):
                result = mod.embed_texts(["a", "b"])
                assert result is not None
                mock.embed.assert_called_once_with(["a", "b"])
        finally:
            mod._provider = old_provider
            mod._provider_failed = old_failed


class TestLocalProviderBehaviour:
    """Exercise LocalProvider's properties and embed path with mocked fastembed."""

    def _make_provider(self):
        """Construct a LocalProvider whose embedder is a controllable mock."""
        fake_fastembed = MagicMock()
        fake_embedder = MagicMock()
        fake_fastembed.TextEmbedding.return_value = fake_embedder
        with patch.dict("sys.modules", {"fastembed": fake_fastembed}):
            from mait_code.tools.memory.embeddings import LocalProvider

            provider = LocalProvider()
        return provider, fake_embedder

    def test_dimension_and_model_name(self):
        """The provider surfaces the configured model name and known dimension."""
        provider, _ = self._make_provider()
        assert provider.dimension == 768
        assert "nomic" in provider.model_name

    def test_embed_converts_arrays_to_lists(self):
        """embed() turns each numpy-style result into a plain list of floats."""
        provider, embedder = self._make_provider()

        # fastembed yields objects with .tolist(); mimic two vectors.
        row_a = MagicMock()
        row_a.tolist.return_value = [0.1, 0.2]
        row_b = MagicMock()
        row_b.tolist.return_value = [0.3, 0.4]
        embedder.embed.return_value = iter([row_a, row_b])

        result = provider.embed(["a", "b"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]


class TestBedrockProvider:
    """Test BedrockProvider graceful degradation."""

    def test_bedrock_dimension_and_model_name(self):
        """BedrockProvider exposes the configured model id and known dimension."""
        from mait_code.tools.memory.embeddings import BedrockProvider

        mock_boto3 = MagicMock()
        with patch.dict(
            "os.environ",
            {"MAIT_CODE_BEDROCK_MODEL_ID": "amazon.titan-embed-text-v2:0"},
        ):
            with patch.dict("sys.modules", {"boto3": mock_boto3}):
                with patch("mait_code.ssl.setup_ssl"):
                    provider = BedrockProvider()

        assert provider.dimension == 1024
        assert provider.model_name == "amazon.titan-embed-text-v2:0"

    def test_bedrock_cohere_payload_and_parse(self):
        """A non-titan (cohere) model uses the texts payload and embeddings key."""
        import json

        from mait_code.tools.memory.embeddings import BedrockProvider

        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"embeddings": [[0.5] * 1024]}
        ).encode()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.dict(
            "os.environ",
            {"MAIT_CODE_BEDROCK_MODEL_ID": "cohere.embed-english-v3"},
        ):
            with patch.dict("sys.modules", {"boto3": mock_boto3}):
                with patch("mait_code.ssl.setup_ssl"):
                    provider = BedrockProvider()
                    result = provider.embed(["test text"])

        assert len(result) == 1
        assert len(result[0]) == 1024
        # Cohere uses the "texts" payload, not Titan's "inputText".
        body = json.loads(mock_client.invoke_model.call_args.kwargs["body"])
        assert body["texts"] == ["test text"]
        assert body["input_type"] == "search_document"

    def test_bedrock_missing_boto3(self):
        """BedrockProvider should fail gracefully if boto3 is missing."""
        import mait_code.tools.memory.embeddings as mod

        old_provider = mod._provider
        old_failed = mod._provider_failed
        mod._provider = None
        mod._provider_failed = False

        try:
            with patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}):
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
        mock_body.read.return_value = json.dumps({"embedding": [0.1] * 1024}).encode()
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


class TestLocalProviderCacheDir:
    """Regression: the local embedder must get an expanded model cache path.

    ``LocalProvider`` builds its fastembed ``cache_dir`` from
    ``get_data_dir() / "models"``. When ``MAIT_CODE_DATA_DIR`` held a literal,
    unexpanded ``~`` the path reached ONNX Runtime as ``~/.claude/...`` and the
    model load failed with ``NO_SUCHFILE`` even though the model existed —
    silently degrading local semantic search. ``config.data_dir()`` now expands
    the tilde; this pins the consumer so the expansion can't regress here.
    """

    def test_cache_dir_is_expanded(self, monkeypatch):
        from mait_code.tools.memory.embeddings import LocalProvider

        monkeypatch.setenv("MAIT_CODE_DATA_DIR", "~/.claude/mait-code-data")

        captured = {}
        fake_fastembed = MagicMock()

        def _capture(*args, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        fake_fastembed.TextEmbedding.side_effect = _capture

        with patch.dict("sys.modules", {"fastembed": fake_fastembed}):
            LocalProvider()

        cache_dir = captured["cache_dir"]
        assert "~" not in cache_dir
        assert cache_dir == str(Path.home() / ".claude" / "mait-code-data" / "models")


class TestDimensionCheck:
    """Test check_dimension_match function.

    Each test pins the provider explicitly so results are deterministic
    regardless of environment configuration.
    """

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_empty_table_matching_declaration_local(self):
        """Empty vec table with dimension matching local provider (768)."""
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
        assert expected == 768

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}, clear=False)
    def test_empty_table_matching_declaration_bedrock(self):
        """Empty vec table with dimension matching bedrock provider (1024)."""
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
        assert matches is True
        assert table_dim == 1024
        assert expected == 1024

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_empty_table_mismatched_declaration(self):
        """Empty vec table with 1024 dim but local provider expects 768."""
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

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_matching_dimension(self):
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        # 768 floats * 4 bytes = 3072 bytes
        conn.execute.return_value.fetchone.return_value = (b"\x00" * (768 * 4),)

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim == 768

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_mismatched_dimension(self):
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        # 1024 floats * 4 bytes = 4096 bytes — mismatch with local 768
        conn.execute.return_value.fetchone.return_value = (b"\x00" * (1024 * 4),)

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is False
        assert table_dim == 1024
        assert expected == 768

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "bedrock"}, clear=False)
    def test_matching_dimension_bedrock(self):
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        # 1024 floats * 4 bytes = 4096 bytes — matches bedrock default
        conn.execute.return_value.fetchone.return_value = (b"\x00" * (1024 * 4),)

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim == 1024

    def test_exception_returns_match(self):
        """If the table doesn't exist, assume it matches."""
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()
        conn.execute.side_effect = Exception("no such table")

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim is None

    @patch.dict("os.environ", {"MAIT_CODE_EMBEDDING_PROVIDER": "local"}, clear=False)
    def test_empty_table_no_declaration_assumes_match(self):
        """Empty vec table whose CREATE sql can't be found assumes a match.

        ``_parse_vec_table_dim`` returns ``None`` when sqlite_master yields no
        row, so ``check_dimension_match`` can't compare and defaults to a match.
        """
        from mait_code.tools.memory.embeddings import check_dimension_match

        conn = MagicMock()

        def _execute(sql, *args):
            result = MagicMock()
            if "sqlite_master" in sql:
                result.fetchone.return_value = None  # no CREATE statement found
            else:
                result.fetchone.return_value = None  # empty memory_vec
            return result

        conn.execute = _execute

        matches, table_dim, expected = check_dimension_match(conn)
        assert matches is True
        assert table_dim is None
        assert expected == 768


class TestParseVecTableDim:
    """The declared-dimension parser swallows query errors."""

    def test_parse_returns_none_on_query_error(self):
        """A connection that raises on the sqlite_master read yields None."""
        from mait_code.tools.memory.embeddings import _parse_vec_table_dim

        conn = MagicMock()
        conn.execute.side_effect = Exception("db gone")
        assert _parse_vec_table_dim(conn) is None
