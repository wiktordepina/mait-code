"""Claude Haiku invocation for structured observation extraction."""

import json
import logging
import re

from mait_code.llm import call_claude

logger = logging.getLogger(__name__)

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
  "bugs_fixed": [
    {"content": "...", "importance": 1-10, "scope": "global|project|branch"}
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
- scope: How broadly this item applies:
  - "global": user-level preferences, personal facts, cross-project knowledge
  - "project": project-specific facts, architecture decisions, conventions
  - "branch": task-specific context, WIP notes, branch-specific bugs
  Hints: preferences are usually global; decisions are usually project-scoped;
  bugs_fixed on feature branches are usually branch-scoped.
- Be specific and concise. Each item should stand alone without context.
- Do NOT extract generic observations. Focus on project-specific, actionable knowledge.
- If the conversation is routine with nothing notable, return all empty arrays.
"""

CONTEXT_HEADER = """\
PROJECT CONTEXT:
Project: {project}
Branch: {branch}

"""

EXPECTED_KEYS = {
    "facts",
    "preferences",
    "decisions",
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
    """Wrap conversation text in the extraction system prompt."""
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
    """Call Claude Haiku via shared LLM module. Returns stdout or None on failure."""
    return call_claude(prompt, model="haiku", timeout=45, retries=2)


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


def extract_observations(
    conversation_text: str,
    *,
    project: str | None = None,
    branch: str | None = None,
) -> dict | None:
    """Full pipeline: build prompt -> call haiku -> parse."""
    prompt = build_extraction_prompt(conversation_text, project=project, branch=branch)
    raw = call_haiku(prompt)
    return parse_extraction(raw)
