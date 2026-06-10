"""Tests for the native auto-memory reader (`tools/memory/native.py`)."""

import os
from pathlib import Path

import pytest

from mait_code.tools.memory.native import (
    list_native_memories,
    native_projects_dir,
    resolve_slug,
)


def _munge(path: Path, root: Path) -> str:
    """A path's munged slug relative to ``root`` (Claude Code's `/` → `-`)."""
    return "-" + str(path.relative_to(root)).replace("/", "-")


class TestNativeProjectsDir:
    def test_defaults_to_home_claude(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        assert native_projects_dir() == Path.home() / ".claude" / "projects"

    def test_honours_claude_config_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert native_projects_dir() == tmp_path / "cfg" / "projects"

    def test_expands_tilde_in_claude_config_dir(self, monkeypatch: pytest.MonkeyPatch):
        # The recurring literal-~ bug class: an env value like "~/.config"
        # must reach consumers expanded.
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", os.path.join("~", ".cc"))
        assert native_projects_dir() == Path.home() / ".cc" / "projects"


class TestResolveSlug:
    def test_resolves_plain_path(self, tmp_path: Path):
        project = tmp_path / "home" / "w" / "projects" / "alpha"
        project.mkdir(parents=True)
        slug = _munge(project, tmp_path)
        assert resolve_slug(slug, root=tmp_path) == project

    def test_backtracks_over_literal_dashes(self, tmp_path: Path):
        # The lossy case: the leaf contains a dash, so the shortest-run walk
        # dead-ends at .../mait and must retry with the joined token.
        project = tmp_path / "home" / "w" / "mait-code"
        project.mkdir(parents=True)
        slug = _munge(project, tmp_path)
        assert resolve_slug(slug, root=tmp_path) == project

    def test_dash_in_intermediate_component(self, tmp_path: Path):
        project = tmp_path / "my-stuff" / "beta"
        project.mkdir(parents=True)
        slug = _munge(project, tmp_path)
        assert resolve_slug(slug, root=tmp_path) == project

    def test_unresolvable_returns_none(self, tmp_path: Path):
        assert resolve_slug("-no-such-path-here", root=tmp_path) is None

    def test_deleted_leaf_returns_none(self, tmp_path: Path):
        (tmp_path / "home" / "w").mkdir(parents=True)
        assert resolve_slug("-home-w-gone", root=tmp_path) is None

    def test_consecutive_dashes_return_none(self, tmp_path: Path):
        # A munged non-slash character (e.g. the dot in ".claude") leaves an
        # empty token the walk can't reconstruct — fall back, don't guess.
        assert resolve_slug("-home-w--claude", root=tmp_path) is None

    def test_empty_slug_returns_none(self, tmp_path: Path):
        assert resolve_slug("", root=tmp_path) is None


class TestListNativeMemories:
    def _seed(self, root: Path, rel: str, files: dict[str, str]) -> Path:
        """Create a fake source project and its munged native memory dir."""
        source = root / "src" / rel
        source.mkdir(parents=True, exist_ok=True)
        slug = _munge(source, root / "src")
        memory_dir = root / "projects" / slug / "memory"
        memory_dir.mkdir(parents=True)
        for name, content in files.items():
            target = memory_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return memory_dir

    def test_missing_projects_dir_yields_empty(self, tmp_path: Path):
        assert list_native_memories(tmp_path / "nowhere") == []

    def test_skips_projects_without_memory(self, tmp_path: Path):
        projects_dir = tmp_path / "projects"
        (projects_dir / "-home-w-empty").mkdir(parents=True)
        (projects_dir / "-home-w-hollow" / "memory").mkdir(parents=True)
        assert list_native_memories(projects_dir) == []

    def test_lists_files_memory_md_first(self, tmp_path: Path):
        self._seed(
            tmp_path,
            "alpha",
            {
                "zebra.md": "# Zebra",
                "MEMORY.md": "# Index",
                "auth-flow.md": "# Auth",
            },
        )
        projects = list_native_memories(tmp_path / "projects")
        assert len(projects) == 1
        names = [f["name"] for f in projects[0]["files"]]
        assert names == ["MEMORY.md", "auth-flow.md", "zebra.md"]

    def test_includes_nested_markdown(self, tmp_path: Path):
        self._seed(tmp_path, "alpha", {"MEMORY.md": "x", "notes/deep.md": "y"})
        projects = list_native_memories(tmp_path / "projects")
        assert [f["name"] for f in projects[0]["files"]] == [
            "MEMORY.md",
            "notes/deep.md",
        ]

    def test_resolves_label_via_root(self, tmp_path: Path):
        self._seed(tmp_path, "mait-code", {"MEMORY.md": "x"})
        projects = list_native_memories(tmp_path / "projects", root=tmp_path / "src")
        assert projects[0]["label"] == "mait-code"
        assert projects[0]["path"] == str(tmp_path / "src" / "mait-code")

    def test_label_falls_back_to_slug(self, tmp_path: Path):
        memory_dir = tmp_path / "projects" / "-home-w-ghost" / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text("x")
        projects = list_native_memories(tmp_path / "projects", root=tmp_path)
        assert projects[0]["label"] == "-home-w-ghost"
        assert projects[0]["path"] is None

    def test_sorted_by_label(self, tmp_path: Path):
        self._seed(tmp_path, "zeta", {"MEMORY.md": "x"})
        self._seed(tmp_path, "Alpha", {"MEMORY.md": "x"})
        projects = list_native_memories(tmp_path / "projects", root=tmp_path / "src")
        assert [p["label"] for p in projects] == ["Alpha", "zeta"]

    def test_file_records_carry_path_and_date(self, tmp_path: Path):
        memory_dir = self._seed(tmp_path, "alpha", {"MEMORY.md": "x"})
        os.utime(memory_dir / "MEMORY.md", (1717200000, 1717200000))  # 2024-06-01
        record = list_native_memories(tmp_path / "projects")[0]["files"][0]
        assert record["path"] == memory_dir / "MEMORY.md"
        assert record["modified"] == "2024-06-01"
