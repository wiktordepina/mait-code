"""Tests for extraction prompt building and JSON parsing."""

import json
from unittest.mock import patch

from mait_code.hooks.observe.extractor import (
    build_extraction_prompt,
    extract_observations,
    parse_extraction,
)


def test_build_extraction_prompt():
    prompt = build_extraction_prompt("USER: hello\nASSISTANT: hi")
    assert "USER: hello" in prompt
    assert "ASSISTANT: hi" in prompt
    assert "facts" in prompt  # Contains the system prompt


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
    with patch("mait_code.hooks.observe.extractor.call_haiku", return_value=None):
        result = extract_observations("USER: hello")
    assert result is None


def test_call_haiku_delegates_to_call_claude():
    """Verify call_haiku passes model='haiku', timeout=45, and retries=2 to call_claude."""
    from mait_code.hooks.observe.extractor import call_haiku

    with patch(
        "mait_code.hooks.observe.extractor.call_claude", return_value="response"
    ) as mock:
        result = call_haiku("test prompt")

    assert result == "response"
    mock.assert_called_once_with("test prompt", model="haiku", timeout=45, retries=2)
