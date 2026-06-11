"""Tests for extraction prompt building and JSON parsing."""

import json
from unittest.mock import patch

from mait_code.hooks.observe.extractor import (
    EXPECTED_KEYS,
    build_extraction_prompt,
    extract_observations,
    parse_extraction,
)


def test_build_extraction_prompt():
    prompt = build_extraction_prompt("USER: hello\nASSISTANT: hi")
    assert "USER: hello" in prompt
    assert "ASSISTANT: hi" in prompt
    assert "facts" in prompt  # Contains the system prompt


def test_prompt_covers_expected_keys():
    """Every key the parser accepts must be asked for in the prompt."""
    prompt = build_extraction_prompt("x")
    for key in EXPECTED_KEYS:
        assert f'"{key}"' in prompt, key


def test_prompt_embeds_canonical_vocabularies():
    """The prompt enums are built from the canonical tuples, not hard-coded."""
    from mait_code.tools.memory.entities import ENTITY_TYPES, RELATIONSHIP_TYPES

    prompt = build_extraction_prompt("x")
    assert "|".join(ENTITY_TYPES) in prompt
    assert "|".join(RELATIONSHIP_TYPES) in prompt
    assert "__ENTITY_TYPES__" not in prompt
    assert "__RELATIONSHIP_TYPES__" not in prompt


def test_prompt_forbids_ephemeral_entities():
    """The guidelines steer the model away from ephemera as entities."""
    prompt = build_extraction_prompt("x")
    assert "version strings" in prompt
    assert "commit hashes" in prompt
    assert "branch names" in prompt


def test_parse_extraction_valid_json():
    raw = json.dumps(
        {
            "facts": [{"content": "uses PostgreSQL", "importance": 7}],
            "preferences": [],
            "decisions": [],
            "bugs_fixed": [],
            "entities": [],
            "relationships": [],
        }
    )
    result = parse_extraction(raw)
    assert result is not None
    assert len(result["facts"]) == 1


def test_parse_extraction_with_code_fences():
    raw = '```json\n{"facts": [], "preferences": [], "decisions": [], "bugs_fixed": [], "entities": [], "relationships": []}\n```'
    result = parse_extraction(raw)
    assert result is not None
    assert isinstance(result["facts"], list)


def test_parse_extraction_with_surrounding_text():
    raw = 'Here is the extraction:\n{"facts": [{"content": "test", "importance": 5}], "preferences": [], "decisions": [], "bugs_fixed": [], "entities": [], "relationships": []}\nHope this helps!'
    result = parse_extraction(raw)
    assert result is not None
    assert len(result["facts"]) == 1


def test_parse_extraction_invalid():
    assert parse_extraction("not json at all") is None
    assert parse_extraction("") is None
    assert parse_extraction(None) is None


def test_parse_extraction_wrong_structure():
    raw = json.dumps({"unrelated": "data"})
    assert parse_extraction(raw) is None


def test_extract_observations_mocked():
    extraction = {
        "facts": [{"content": "uses uv for packaging", "importance": 6}],
        "preferences": [],
        "decisions": [],
        "bugs_fixed": [],
        "entities": [
            {"name": "uv", "entity_type": "tool", "context": "Python packaging"}
        ],
        "relationships": [],
    }
    mock_stdout = json.dumps(extraction)

    with patch(
        "mait_code.hooks.observe.extractor.call_haiku", return_value=mock_stdout
    ):
        result = extract_observations("USER: we use uv\nASSISTANT: noted")

    assert result is not None
    assert len(result["facts"]) == 1
    assert result["entities"][0]["name"] == "uv"


def test_extract_observations_haiku_failure():
    """A transport failure (call_haiku returns None) propagates as None — retryable."""
    with patch("mait_code.hooks.observe.extractor.call_haiku", return_value=None):
        result = extract_observations("USER: hello")
    assert result is None


def test_extract_observations_unparseable_returns_empty():
    """A response that can't be parsed is handled ({}), not a transport failure (None)."""
    with patch(
        "mait_code.hooks.observe.extractor.call_haiku", return_value="not json at all"
    ):
        result = extract_observations("USER: hello")
    assert result == {}


def test_call_haiku_delegates_to_call_claude(monkeypatch):
    """call_haiku passes the configured extraction model and retries=2.

    Timeout is left to call_claude (which reads the llm-timeout setting).
    """
    from mait_code import config
    from mait_code.hooks.observe.extractor import call_haiku

    monkeypatch.setattr(config, "_settings_cache", {})
    monkeypatch.delenv("MAIT_CODE_EXTRACTION_MODEL", raising=False)

    with patch(
        "mait_code.hooks.observe.extractor.call_claude", return_value="response"
    ) as mock:
        result = call_haiku("test prompt")

    assert result == "response"
    mock.assert_called_once_with("test prompt", model="haiku", retries=2)


def test_call_haiku_honours_extraction_model_setting(monkeypatch):
    from mait_code import config
    from mait_code.hooks.observe.extractor import call_haiku

    monkeypatch.setattr(config, "_settings_cache", {})
    monkeypatch.setenv("MAIT_CODE_EXTRACTION_MODEL", "sonnet")

    with patch(
        "mait_code.hooks.observe.extractor.call_claude", return_value="r"
    ) as mock:
        call_haiku("p")

    assert mock.call_args[1]["model"] == "sonnet"
