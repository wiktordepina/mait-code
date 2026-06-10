"""Scope resolution for extracted observations.

Determines the appropriate scope (global/project/branch) for each
extracted item using LLM classification with heuristic fallback.
"""

VALID_SCOPES = {"global", "project", "branch"}


def resolve_scope(
    item: dict,
    category: str,
    project: str | None,
    branch: str | None,
) -> str:
    """Determine the scope for an extracted observation item.

    Strategy: trust the LLM's scope classification when it is valid, then fall
    back to per-category heuristics.

    Args:
        item: Extracted item dict (may contain "scope" from LLM).
        category: Extraction category (facts, preferences, decisions,
            procedures, bugs_fixed).
        project: Current project identifier, or None.
        branch: Current branch name, or None.

    Returns:
        One of "global", "project", "branch".
    """
    # No project context — everything is global
    if project is None:
        return "global"

    # Trust LLM classification if valid
    llm_scope = item.get("scope", "").strip().lower()
    if llm_scope in VALID_SCOPES:
        return llm_scope

    # Heuristic fallbacks when the LLM gave nothing usable
    if category == "preferences":
        # Preferences are usually global; only narrow when the LLM said so
        # (handled above). This is the fallback, not an override.
        return "global"

    if category == "decisions":
        return "project"

    if category == "procedures":
        # Project workflows are the common case; the LLM marks the
        # user-level ones global (handled above).
        return "project"

    if category == "bugs_fixed" and branch is not None:
        return "branch"

    # Default: branch if available, otherwise project
    if branch is not None:
        return "branch"
    return "project"
