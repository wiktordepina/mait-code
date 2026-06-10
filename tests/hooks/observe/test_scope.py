"""Tests for scope resolution heuristics."""

from mait_code.hooks.observe.scope import resolve_scope


class TestResolveScope:
    def test_no_project_always_global(self):
        """Without project context, everything is global."""
        assert resolve_scope({"content": "x"}, "facts", None, None) == "global"
        assert (
            resolve_scope({"content": "x"}, "bugs_fixed", None, "feature/a") == "global"
        )

    def test_preferences_fallback_global(self):
        """Preferences with no usable LLM scope fall back to global."""
        assert (
            resolve_scope({"content": "x"}, "preferences", "proj", "feature/a")
            == "global"
        )
        assert resolve_scope({"content": "x"}, "preferences", "proj", None) == "global"

    def test_trusts_llm_scope(self):
        """Valid LLM scope should be used."""
        item = {"content": "x", "scope": "global"}
        assert resolve_scope(item, "facts", "proj", "feature/a") == "global"

        item = {"content": "x", "scope": "project"}
        assert resolve_scope(item, "facts", "proj", "feature/a") == "project"

        item = {"content": "x", "scope": "branch"}
        assert resolve_scope(item, "facts", "proj", "feature/a") == "branch"

    def test_invalid_llm_scope_falls_through(self):
        """Invalid LLM scope should be ignored."""
        item = {"content": "x", "scope": "invalid"}
        # With branch -> default branch
        assert resolve_scope(item, "facts", "proj", "feature/a") == "branch"

    def test_decisions_default_project(self):
        """Decisions default to project scope."""
        assert (
            resolve_scope({"content": "x"}, "decisions", "proj", "feature/a")
            == "project"
        )
        assert resolve_scope({"content": "x"}, "decisions", "proj", None) == "project"

    def test_decisions_respect_llm_scope(self):
        """Decisions honour a valid LLM scope; project is only the fallback default."""
        # LLM says branch for a decision — should be trusted
        item = {"content": "x", "scope": "branch"}
        assert resolve_scope(item, "decisions", "proj", "feature/a") == "branch"

    def test_procedures_default_project(self):
        """Procedures default to project scope, even on a branch."""
        assert (
            resolve_scope({"content": "x"}, "procedures", "proj", "feature/a")
            == "project"
        )
        assert resolve_scope({"content": "x"}, "procedures", "proj", None) == "project"

    def test_procedures_respect_llm_scope(self):
        """Procedures honour a valid LLM scope; project is only the fallback."""
        item = {"content": "x", "scope": "global"}
        assert resolve_scope(item, "procedures", "proj", "feature/a") == "global"

    def test_bugs_fixed_on_branch_defaults_branch(self):
        """Bugs fixed on a feature branch default to branch scope."""
        assert (
            resolve_scope({"content": "x"}, "bugs_fixed", "proj", "feature/a")
            == "branch"
        )

    def test_bugs_fixed_no_branch_defaults_project(self):
        """Bugs fixed without branch context default to project scope."""
        assert resolve_scope({"content": "x"}, "bugs_fixed", "proj", None) == "project"

    def test_facts_with_branch_default_branch(self):
        """Facts on a branch default to branch scope."""
        assert resolve_scope({"content": "x"}, "facts", "proj", "feature/a") == "branch"

    def test_facts_without_branch_default_project(self):
        """Facts without branch default to project scope."""
        assert resolve_scope({"content": "x"}, "facts", "proj", None) == "project"

    def test_missing_scope_field(self):
        """Items without scope field should use heuristics."""
        assert resolve_scope({"content": "x"}, "facts", "proj", "feature/a") == "branch"

    def test_preferences_respect_llm_scope(self):
        """A preference the LLM scopes to project/branch is honoured (no override)."""
        assert (
            resolve_scope(
                {"content": "x", "scope": "branch"}, "preferences", "proj", "feature/a"
            )
            == "branch"
        )
        assert (
            resolve_scope(
                {"content": "x", "scope": "project"}, "preferences", "proj", None
            )
            == "project"
        )
