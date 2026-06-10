"""Claude Haiku invocation for structured observation extraction."""

import json
import logging
import re

from mait_code.config import get as config_get
from mait_code.llm import call_claude
from mait_code.tools.memory.entities import RELATIONSHIP_TYPES

logger = logging.getLogger(__name__)

# Built from the canonical vocabulary so the prompt and the write-time
# enforcement in storage.py can never drift apart.
_RELATIONSHIP_TYPES_STR = "|".join(RELATIONSHIP_TYPES)

EXTRACTION_PROMPT = """\
You are an observation extraction system. Analyze the following conversation
and extract notable information as structured JSON.

Return ONLY a JSON object with these arrays (use empty arrays if none found):

{
  "facts": [
    {"content": "...", "importance": 1-10, "scope": "global|project|branch"}
  ],
  "preferences": [
    {"content": "...", "importance": 1-10, "scope": "global|project|branch"}
  ],
  "decisions": [
    {"content": "...", "importance": 1-10, "scope": "global|project|branch"}
  ],
  "procedures": [
    {"content": "...", "importance": 1-10, "scope": "global|project|branch"}
  ],
  "bugs_fixed": [
    {"content": "...", "importance": 1-10, "scope": "global|project|branch"}
  ],
  "entities": [
    {"name": "...", "entity_type": "person|project|tool|service|concept|org", "context": "..."}
  ],
  "relationships": [
    {"source": "entity name", "target": "entity name", "relationship_type": "__RELATIONSHIP_TYPES__", "context": "..."}
  ]
}

Guidelines:
- facts: Technical facts about the codebase, architecture, or environment
- preferences: User preferences about tools, workflows, coding style
- decisions: Architectural or design decisions made during the session
- procedures: Repeatable workflows or how-tos worth reusing — the steps or
  recipe for getting something done ("to debug X: check Y first, then Z").
  Boundary: if it answers "how do I do X next time?" it is a procedure; if it
  answers "what did we pick?" it is a decision; if it answers "what does the
  user like?" it is a preference.
- bugs_fixed: Bugs identified and fixed, with root cause if mentioned
- entities: People, projects, tools, services, or concepts discussed
- relationships: How entities relate to each other
- importance: 1=trivial, 5=moderate, 8=significant, 10=critical
- scope: How broadly this item applies:
  - "global": user-level preferences, personal facts, cross-project knowledge
  - "project": project-specific facts, architecture decisions, conventions
  - "branch": task-specific context, WIP notes, branch-specific bugs
  Hints: preferences are usually global; decisions are usually project-scoped;
  procedures about the user's general workflow are global, project workflows
  are project-scoped; bugs_fixed on feature branches are usually branch-scoped.
- Be specific and concise. Each item should stand alone without context.
- Do NOT extract generic observations. Focus on project-specific, actionable knowledge.
- If the conversation is routine with nothing notable, return all empty arrays.
""".replace("__RELATIONSHIP_TYPES__", _RELATIONSHIP_TYPES_STR)

CONTEXT_HEADER = """\
PROJECT CONTEXT:
Project: {project}
Branch: {branch}

"""

EXPECTED_KEYS = {
    "facts",
    "preferences",
    "decisions",
    "procedures",
    "bugs_fixed",
    "entities",
    "relationships",
}


def build_extraction_prompt(
    conversation_text: str,
    *,
    project: str | None = None,
    branch: str | None = None,
) -> str:
    """Wrap conversation text in the extraction system prompt.

    Args:
        conversation_text: Formatted conversation transcript.
        project: Project identifier to include in the context header.
        branch: Branch name to include in the context header.

    Returns:
        The full extraction prompt ready to pass to the LLM.
    """
    parts = [EXTRACTION_PROMPT]
    if project:
        parts.append(
            CONTEXT_HEADER.format(project=project, branch=branch or "(default branch)")
        )
    parts.append("<CONVERSATION>\n")
    parts.append(conversation_text)
    parts.append("\n</CONVERSATION>")
    return "".join(parts)


def call_haiku(prompt: str) -> str | None:
    """Call the configured extraction model via the shared LLM module.

    The model is the ``extraction-model`` setting (default ``haiku``); the
    timeout follows the ``llm-timeout`` setting.

    Args:
        prompt: The full extraction prompt to send.

    Returns:
        Stripped stdout from the model, or ``None`` on failure.
    """
    return call_claude(prompt, model=config_get("extraction-model"), retries=2)


def parse_extraction(raw_output: str) -> dict | None:
    """Parse JSON from Haiku's response, tolerating markdown code fences.

    Args:
        raw_output: The raw stdout returned by Haiku.

    Returns:
        The parsed extraction dict, or ``None`` if the response cannot be
        parsed into a dict containing any of the expected keys.
    """
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


def extract_observations(
    conversation_text: str,
    *,
    project: str | None = None,
    branch: str | None = None,
) -> dict | None:
    """Run the full extraction pipeline: build prompt, call Haiku, parse.

    Args:
        conversation_text: Formatted conversation transcript.
        project: Project identifier passed into the prompt header.
        branch: Branch name passed into the prompt header.

    Returns:
        ``None`` if the LLM call itself failed (timeout / non-zero exit) — a
        transient failure the caller should retry by leaving the cursor put.
        ``{}`` if the model responded but its output could not be parsed (the
        call succeeded, so treat the window as handled). The parsed extraction
        dict on success — its arrays may be empty when nothing was notable.
    """
    prompt = build_extraction_prompt(conversation_text, project=project, branch=branch)
    raw = call_haiku(prompt)
    if raw is None:
        # Transport failure (timeout / non-zero exit) — signal "retry me".
        return None
    parsed = parse_extraction(raw)
    if parsed is None:
        # Responded but unparseable; retrying is unlikely to help.
        return {}
    return parsed
