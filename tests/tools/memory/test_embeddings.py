"""Tests for the embeddings module."""

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


class TestConstants:
    def test_model_name(self):
        assert "nomic" in EMBEDDING_MODEL

    def test_dimension(self):
        assert EMBEDDING_DIM == 768


class TestGracefulDegradation:
    def test_embed_text_returns_none_when_unavailable(self):
        """embed_text should return None if fastembed fails to load."""
        import mait_code.tools.memory.embeddings as mod

        # Reset module state
        old_embedder = mod._embedder
        old_failed = mod._embedder_failed
        mod._embedder = None
        mod._embedder_failed = False

        try:
            with patch.dict("sys.modules", {"fastembed": None}):
                mod._embedder_failed = False  # Reset so it tries again
                result = mod.embed_text("test text")
                # When fastembed import fails, should return None
                # (the import error sets _embedder_failed)
                assert result is None
        finally:
            mod._embedder = old_embedder
            mod._embedder_failed = old_failed

    def test_embed_texts_returns_none_when_unavailable(self):
        """embed_texts should return None if embedder is unavailable."""
        import mait_code.tools.memory.embeddings as mod

        old_embedder = mod._embedder
        old_failed = mod._embedder_failed
        mod._embedder = None
        mod._embedder_failed = True

        try:
            result = mod.embed_texts(["test"])
            assert result is None
        finally:
            mod._embedder = old_embedder
            mod._embedder_failed = old_failed

    def test_is_available_false_when_failed(self):
        """is_available should return False if embedder failed."""
        import mait_code.tools.memory.embeddings as mod

        old_embedder = mod._embedder
        old_failed = mod._embedder_failed
        mod._embedder = None
        mod._embedder_failed = True

        try:
            assert mod.is_available() is False
        finally:
            mod._embedder = old_embedder
            mod._embedder_failed = old_failed


class TestEmbedWithMock:
    """Test embed functions with a mocked embedder."""

    def _make_mock_embedder(self):
        import numpy as np

        embedder = MagicMock()
        embedder.embed.return_value = [np.zeros(768, dtype="float32")]
        return embedder

    def test_embed_text_prepends_prefix(self):
        import mait_code.tools.memory.embeddings as mod

        old_embedder = mod._embedder
        old_failed = mod._embedder_failed
        mock = self._make_mock_embedder()
        mod._embedder = mock
        mod._embedder_failed = False

        try:
            result = mod.embed_text("hello world", prefix="search_query")
            assert result is not None
            assert len(result) == 768
            mock.embed.assert_called_once_with(["search_query: hello world"])
        finally:
            mod._embedder = old_embedder
            mod._embedder_failed = old_failed

    def test_embed_text_default_prefix(self):
        import mait_code.tools.memory.embeddings as mod

        old_embedder = mod._embedder
        old_failed = mod._embedder_failed
        mock = self._make_mock_embedder()
        mod._embedder = mock
        mod._embedder_failed = False

        try:
            mod.embed_text("hello world")
            mock.embed.assert_called_once_with(["search_document: hello world"])
        finally:
            mod._embedder = old_embedder
            mod._embedder_failed = old_failed

    def test_embed_texts_batch(self):
        import numpy as np

        import mait_code.tools.memory.embeddings as mod

        old_embedder = mod._embedder
        old_failed = mod._embedder_failed
        mock = MagicMock()
        mock.embed.return_value = [
            np.zeros(768, dtype="float32"),
            np.ones(768, dtype="float32"),
        ]
        mod._embedder = mock
        mod._embedder_failed = False

        try:
            result = mod.embed_texts(["a", "b"], prefix="search_document")
            assert result is not None
            assert len(result) == 2
            assert len(result[0]) == 768
            mock.embed.assert_called_once_with(
                ["search_document: a", "search_document: b"]
            )
        finally:
            mod._embedder = old_embedder
            mod._embedder_failed = old_failed
