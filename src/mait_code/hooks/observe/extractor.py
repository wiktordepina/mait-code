"""Claude Haiku invocation for structured observation extraction."""

import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """\
You are an observation extraction system. Analyze the following conversation
and extract notable information as structured JSON.

Return ONLY a JSON object with these arrays (use empty arrays if none found):

{
  "facts": [
    {"content": "...", "importance": 1-10}
  ],
  "preferences": [
    {"content": "...", "importance": 1-10}
  ],
  "decisions": [
    {"content": "...", "importance": 1-10}
  ],
  "bugs_fixed": [
    {"content": "...", "importance": 1-10}
  ],
  "entities": [
    {"name": "...", "entity_type": "person|project|tool|service|concept|org", "context": "..."}
  ],
  "relationships": [
    {"source": "entity name", "target": "entity name", "relationship_type": "uses|owns|contributes_to|depends_on|manages|related_to", "context": "..."}
  ]
}

Guidelines:
- facts: Technical facts about the codebase, architecture, or environment
- preferences: User preferences about tools, workflows, coding style
- decisions: Architectural or design decisions made during the session
- bugs_fixed: Bugs identified and fixed, with root cause if mentioned
- entities: People, projects, tools, services, or concepts discussed
- relationships: How entities relate to each other
- importance: 1=trivial, 5=moderate, 8=significant, 10=critical
- Be specific and concise. Each item should stand alone without context.
- Do NOT extract generic observations. Focus on project-specific, actionable knowledge.
- If the conversation is routine with nothing notable, return all empty arrays.

CONVERSATION:
"""

EXPECTED_KEYS = {
    "facts",
    "preferences",
    "decisions",
    "bugs_fixed",
    "entities",
    "relationships",
}


def build_extraction_prompt(conversation_text: str) -> str:
    """Wrap conversation text in the extraction system prompt."""
    return EXTRACTION_PROMPT + conversation_text


def call_haiku(prompt: str) -> str | None:
    """Call claude -p --model haiku. Returns stdout or None on failure."""
    try:
        # Clear CLAUDECODE env var to allow nested claude invocations from hooks
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
        if result.returncode != 0:
            logger.warning("claude exited %d: %s", result.returncode, result.stderr[:200] if result.stderr else "")
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        logger.error("claude CLI not found")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("claude timed out")
        return None


def parse_extraction(raw_output: str) -> dict | None:
    """Parse JSON from Haiku's response, handling code fences."""
    if not raw_output:
        return None

    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw_output, flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)

    # Try direct parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and EXPECTED_KEYS & set(data):
            return data
    except json.JSONDecodeError:
        pass

    # Fallback: find JSON object in response
    match = re.search(r"\{[\s\S]*\}", raw_output)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and EXPECTED_KEYS & set(data):
                return data
        except json.JSONDecodeError:
            pass

    logger.warning("failed to parse extraction JSON: %s", raw_output[:200])
    return None


def extract_observations(conversation_text: str) -> dict | None:
    """Full pipeline: build prompt -> call haiku -> parse."""
    prompt = build_extraction_prompt(conversation_text)
    raw = call_haiku(prompt)
    return parse_extraction(raw)
