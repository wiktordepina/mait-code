"""Interactive ``mait-code review`` &mdash; work the memory review queue.

A full-screen master&ndash;detail surface over the *due-for-review* set
(:func:`mait_code.tools.memory.review.due_for_review`): a queue of
important-but-ageing memories on the left, most-decayed first, and the
highlighted memory's body plus its review-relevant metadata on the right.
Unlike the read-only memory browser, this surface **acts** — each decision
writes through an existing store-writer verb:

* **confirm** (still true) → :func:`~mait_code.tools.memory.writer.mark_reviewed`
* **refine** (edit &amp; save) → :func:`~mait_code.tools.memory.writer.supersede_memory`
* **retire** (no longer true) → :func:`~mait_code.tools.memory.writer.retire_memory`
* **skip** — just navigate on, nothing written.

A decided memory drops out of the queue and the cursor advances; when the
queue empties the pane shows an all-caught-up state. Reviewing resets a
memory's resurfacing decay curve, so it stops surfacing until a fresh
half-life passes.

The app holds one connection for its lifetime for reads and the two instant
writes (confirm, retire); *refine* supersedes on a short-lived connection in a
worker thread, because ``supersede_memory`` embeds the new entry inline (a
local-model call or network round-trip) and that must not stall the event
loop. Requires a TTY; the bare ``review`` command only routes here when
attached to one, falling back to a text list otherwise.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Label, Markdown, Static, TextArea, Tree
from textual.widgets.tree import TreeNode

from mait_code.tools.memory.db import get_connection
from mait_code.tools.memory.review import due_for_review
from mait_code.tools.memory.search import list_projects
from mait_code.tools.memory.writer import mark_reviewed, retire_memory, supersede_memory
from mait_code.tui import palette
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state
from mait_code.tui.confirm import ConfirmScreen
from mait_code.tui.filters import ProjectFilterScreen
from mait_code.tui.markdown import md_parser
from mait_code.tui.palette import rich_colour

__all__ = ["ReviewApp", "run_review_tui"]


def run_review_tui(db_path: Path | None = None) -> None:
    """Launch the Textual memory-review TUI (blocks until the user quits)."""
    ReviewApp(db_path=db_path).run()


def _scope_label(entry: dict) -> str:
    """Format an entry's scope like ``mc-tool-memory``: ``global``,
    ``<project>``, or ``<project>:<branch>``."""
    scope = entry.get("scope") or "global"
    project = entry.get("project")
    branch = entry.get("branch")
    if scope == "global" or not project:
        return "global"
    if scope == "branch" and branch:
        return f"{project}:{branch}"
    return project


#: A queue leaf clips its content preview to this width so the tree never
#: forces a horizontal scroll on a sane split (matches the memory browser).
_LEAF_WIDTH = 56

#: Below this recall probability a memory reads as *most* decayed and its
#: badge takes the error hue rather than the warning one — a small visual
#: gradient across the queue, which is already sorted lowest-recall first.
_URGENT_RECALL = 0.25


def _clip(line: str) -> str:
    """Clip a preview line to :data:`_LEAF_WIDTH` with an ellipsis."""
    if len(line) > _LEAF_WIDTH:
        return line[: _LEAF_WIDTH - 1] + "…"
    return line


class RefineScreen(ModalScreen[str | None]):
    """Edit a memory's content, resolving to the new text (or ``None`` cancel).

    A small editor modal: the entry's body prefills a :class:`TextArea`;
    ``ctrl+s`` (or **Save**) resolves to the edited text, ``escape`` (or
    **Cancel**) resolves to ``None``. The caller supersedes the entry with the
    returned text — this screen never touches the store itself.
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, entry: dict) -> None:
        super().__init__()
        self._entry = entry

    def compose(self) -> ComposeResult:
        entry = self._entry
        with Vertical(id="refine-dialog", classes="modal-dialog"):
            yield Label(
                f"Refine #{entry['id']} · {entry['entry_type']}",
                classes="modal-title",
            )
            yield Label(
                "Edit the memory, then save to supersede it with the new "
                "version. Saving resets its review curve.",
                classes="modal-help",
            )
            yield TextArea(entry["content"], id="refine-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#refine-input", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()

    def action_save(self) -> None:
        self.dismiss(self.query_one("#refine-input", TextArea).text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ReviewApp(MaitApp):
    """Master–detail surface for working the memory review queue."""

    TITLE = "mait-code review"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_review.tcss"]

    BINDINGS = [
        Binding("c", "confirm", "Confirm"),
        Binding("e", "refine", "Refine"),
        Binding("x", "retire", "Retire"),
        ("p", "filter_project", "Project"),
        ("r", "reload", "Reload"),
    ]

    def __init__(
        self, db_path: Path | None = None, now: datetime | None = None
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._conn = get_connection(db_path)  # one connection for reads + fast writes
        # Injected clock: the queue's recall is measured against this. None →
        # real UTC now (production); the snapshot/behaviour tests pin it so the
        # due set and its recall figures never drift with wall-clock.
        self._now = now
        self._project: str | None = None
        self._due: list[dict] = []

    def on_unmount(self) -> None:
        super().on_unmount()  # persists the active theme (MaitApp)
        self._conn.close()

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Review")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                yield Tree("due for review", id="queue")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        tree: Tree[dict] = self.query_one("#queue", Tree)
        tree.show_root = False
        tree.guide_depth = 2
        self._load_due()
        self._rebuild(land_index=0)
        tree.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # The per-item verbs only make sense with a memory under the cursor.
        if action in ("confirm", "refine", "retire"):
            return bool(self._due)
        return True

    # -- data ------------------------------------------------------------------

    def _load_due(self) -> None:
        """(Re)compute the due queue — everything, unless narrowed to a project."""
        self._due = due_for_review(self._conn, now=self._now, project=self._project)

    def _colours(self) -> dict[str, str]:
        """The active theme's warn/urgent hues (Rich-safe), with house fallbacks."""
        theme = self.get_theme(self.theme)
        return {
            "warn": rich_colour(theme.warning if theme else None, palette.WARNING),
            "urgent": rich_colour(theme.error if theme else None, palette.ERROR),
        }

    def _leaf_label(self, entry: dict, colours: dict[str, str]) -> Text:
        """One queue row: dimmed id, a recall-% badge, then a content preview."""
        first_line = (
            entry["content"].strip().splitlines()[0] if entry["content"] else ""
        )
        recall_pct = round(entry["recall"] * 100)
        hue = colours["urgent"] if entry["recall"] < _URGENT_RECALL else colours["warn"]
        label = Text(no_wrap=True)
        label.append(f"#{entry['id']}  ", style="dim")
        # The trailing gap rides inside the styled run so renderers that trim a
        # run's leading whitespace can't swallow the separation (as elsewhere).
        label.append(f"{recall_pct}%  ", style=hue)
        label.append(_clip(first_line))
        return label

    # -- tree ------------------------------------------------------------------

    def _rebuild(self, *, land_index: int) -> None:
        """Repopulate the queue and land the cursor near ``land_index``.

        After a decision the acted-on row is gone, so the same index now points
        at the memory that shifted up into its place — clamped to the new end.
        An empty queue collapses to the all-caught-up state instead.
        """
        tree: Tree[dict] = self.query_one("#queue", Tree)
        tree.root.remove_children()
        self._update_subtitle()

        if not self._due:
            self.call_after_refresh(self._show_empty)
            self.refresh_bindings()  # confirm/refine/retire drop from the footer
            return

        colours = self._colours()
        leaves: list[TreeNode[dict]] = [
            tree.root.add_leaf(self._leaf_label(entry, colours), data=entry)
            for entry in self._due
        ]
        target = leaves[min(land_index, len(leaves) - 1)]
        # Deferred until after the first refresh: the tree's visible-line map
        # (which move_cursor indexes into) isn't built until then, and landing
        # on the same line index emits no NodeHighlighted, so the detail render
        # is explicit rather than left to the highlight event.
        self.call_after_refresh(tree.move_cursor, target)
        self.call_after_refresh(self._show_detail, target.data)
        self.refresh_bindings()

    def _update_subtitle(self) -> None:
        n = len(self._due)
        text = f"Review — {n} to review" if n else "Review — all caught up"
        if self._project:
            text += f" · {self._project}"
        self.query_one(BrandBanner).set_subtitle(text)

    def _current_entry(self) -> dict | None:
        """The memory under the cursor, or ``None`` when the queue is empty."""
        node = self.query_one("#queue", Tree).cursor_node
        return node.data if node is not None else None

    def _current_index(self) -> int:
        """The cursor's line index — where to re-land after a decision."""
        return self.query_one("#queue", Tree).cursor_line

    # -- detail ----------------------------------------------------------------

    async def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is not None:
            await self._show_detail(event.node.data)

    async def _show_detail(self, entry: dict) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        recall_pct = round(entry["recall"] * 100)
        # Recall leads — it's why the memory is in the queue, so it must never
        # be the token that clips off a narrow pane. Scope is shown only when
        # it's not the (common, uninteresting) global case.
        parts = [
            f"recall {recall_pct}%",
            f"reviewed {str(entry['reviewed_at'])[:10]}",
            f"importance {entry['importance']}",
            entry["memory_class"],
        ]
        scope = _scope_label(entry)
        if scope != "global":
            parts.append(f"scope {scope}")
        meta = " · ".join(parts)
        await detail.mount(
            Label(f"#{entry['id']} · {entry['entry_type']}", classes="title"),
            Label(meta, classes="help"),
            # Markdown, not Static: plain text is valid markdown, and stored
            # content that *is* markdown renders properly (as the browser does).
            Markdown(entry["content"], parser_factory=md_parser, open_links=False),
        )

    async def _show_empty(self) -> None:
        detail = self.query_one("#detail", VerticalScroll)
        await detail.remove_children()
        if self._project:
            message = f"Nothing due for {self._project} — its memory is fresh."
        else:
            message = "All caught up — curated memory is fresh."
        await detail.mount(Static(empty_state(message), classes="help"))

    # -- decisions -------------------------------------------------------------

    def _drop(self, entry_id: int) -> None:
        """Remove a decided memory from the in-memory queue."""
        self._due = [e for e in self._due if e["id"] != entry_id]

    def action_confirm(self) -> None:
        """Confirm the current memory is still true — reset its review curve."""
        entry = self._current_entry()
        if entry is None:
            return
        index = self._current_index()
        result = mark_reviewed(self._conn, entry["id"])
        if result["action"] == "reviewed":
            self._drop(entry["id"])
            self._rebuild(land_index=index)
            self.notify(
                f"Confirmed #{entry['id']} — review curve reset.", title="Review"
            )
        else:
            self._resync(index, f"#{entry['id']} is already gone.")

    @work
    async def action_retire(self) -> None:
        """Retire the current memory — drop it from recall, after a confirm."""
        entry = self._current_entry()
        if entry is None:
            return
        index = self._current_index()
        ok = await self.push_screen_wait(
            ConfirmScreen(f"Retire #{entry['id']}? It'll be hidden from recall.")
        )
        if not ok:
            return
        result = retire_memory(self._conn, entry["id"])
        if result["action"] == "retired":
            self._drop(entry["id"])
            self._rebuild(land_index=index)
            self.notify(f"Retired #{entry['id']}.", title="Review")
        else:
            self._resync(index, f"Couldn't retire #{entry['id']} ({result['action']}).")

    @work
    async def action_refine(self) -> None:
        """Edit the current memory and supersede it with the new version."""
        entry = self._current_entry()
        if entry is None:
            return
        index = self._current_index()
        new_text = await self.push_screen_wait(RefineScreen(entry))
        if new_text is None:
            return  # cancelled
        new_text = new_text.strip()
        if not new_text:
            self.notify(
                "Empty content — nothing saved.", severity="warning", title="Review"
            )
            return
        if new_text == entry["content"].strip():
            self.notify("No change — nothing saved.", title="Review")
            return
        # supersede_memory embeds the new entry inline; run it off the UI thread
        # on a fresh connection (sqlite connections are single-thread) so the
        # loop stays responsive while the model loads.
        worker = self.run_worker(
            partial(self._supersede_write, entry["id"], new_text),
            thread=True,
            exclusive=False,
        )
        result = await worker.wait()
        if result and result.get("action") == "superseded":
            self._drop(entry["id"])
            self._rebuild(land_index=index)
            self.notify(f"Refined #{entry['id']} → #{result['id']}.", title="Review")
        else:
            self._resync(index, f"Couldn't refine #{entry['id']}.")

    def _supersede_write(self, entry_id: int, content: str) -> dict:
        """Supersede on a short-lived connection — runs in a worker thread."""
        conn = get_connection(self._db_path)
        try:
            return supersede_memory(conn, entry_id, content)
        finally:
            conn.close()

    def _resync(self, index: int, message: str) -> None:
        """Recover from a write that didn't land: re-read and re-render.

        A ``not_found`` / ``already_*`` outcome means the store changed under
        us (another process, or a stale row). Recompute the queue so what's on
        screen matches the store, and tell the user why.
        """
        self._load_due()
        self._rebuild(land_index=index)
        self.notify(message, severity="warning", title="Review")

    # -- filtering / reload ----------------------------------------------------

    @work
    async def action_filter_project(self) -> None:
        """Narrow the queue to one project's memories (or clear the filter)."""
        projects = list_projects(self._conn)
        result = await self.push_screen_wait(
            ProjectFilterScreen(projects, self._project)
        )
        if result is None:
            return  # escape/cancel — leave the active filter as-is
        # A project name filters to it; the ALL_PROJECTS sentinel clears it.
        self._project = result if isinstance(result, str) else None
        self._load_due()
        self._rebuild(land_index=0)
        self.query_one("#queue", Tree).focus()

    def action_reload(self) -> None:
        """Recompute the queue — picks up memories reviewed elsewhere."""
        index = self._current_index()
        self._load_due()
        self._rebuild(land_index=index)
        self.notify("Review queue recomputed", title="Review")

    def get_system_commands(self, screen: Screen):
        """Expose the review actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Filter by project",
            "Narrow the queue to one project",
            self.action_filter_project,
        )
        yield SystemCommand("Reload", "Recompute the due queue", self.action_reload)
