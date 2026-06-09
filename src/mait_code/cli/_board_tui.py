"""Interactive ``mait-code board`` &mdash; a Textual kanban TUI.

A full-screen, on-demand board: one column-pane per status laid side by side,
every project's cards visible with a project filter, keyboard navigation, and
move / comment / tag / block gestures. It runs in the foreground and exits on ``q``
&mdash; no background process &mdash; mirroring the ``mait-code settings`` editor.

Every query and mutation delegates to
:mod:`mait_code.tools.board.service`, so the done-invariant and the SQL live in
one place; this module owns only presentation. The app holds a single
connection for its lifetime (opened in ``__init__``, closed on unmount).

Requires a TTY; the bare ``board`` command only routes here when attached to
one, falling back to a read-only render otherwise.
"""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path

import rich.box
from rich.console import Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    Markdown,
    OptionList,
    RadioButton,
    RadioSet,
    Rule,
    Select,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option, OptionDoesNotExist

from mait_code.tools.board import export, service
from mait_code.tools.board.columns import (
    ARCHIVED,
    BACKLOG,
    BLOCKED_TAG,
    BOARD_ORDER,
    DONE,
    IN_PROGRESS,
    REFINED,
    label as col_label,
)
from mait_code.tools.board.db import get_connection, get_project
from mait_code.tui import palette as p
from mait_code.tui.app import SHARED_TCSS, MaitApp
from mait_code.tui.banner import BrandBanner
from mait_code.tui.brand import empty_state
from mait_code.tui.markdown import md_parser
from mait_code.tui.render import (
    PALETTE_CHIPS,
    ChipColours,
    priority_chip,
    tag_badge,
)

__all__ = ["BoardApp", "run_board_tui"]

#: Every pane shown, in left-to-right order. ``archived`` is the hidden last
#: pane, revealed by the ``a`` toggle.
_PANES: tuple[str, ...] = (*BOARD_ORDER, ARCHIVED)

#: The linear flow the ``<``/``>`` keys move a card along — every real status
#: except the hidden ``archived`` side-state, which is reached only via the CLI.
_MOVE_FLOW: tuple[str, ...] = (BACKLOG, REFINED, IN_PROGRESS, DONE)

#: Sentinel ``Select`` value for the "show every project" option in the project
#: filter picker. A distinct object (not ``None``) so the picker can tell "all
#: projects" apart from the ``None`` that escape/cancel dismisses with.
_ALL_PROJECTS = object()

#: Companion-voice hint shown (dim, non-selectable) in an empty column, so a
#: bare pane still sounds like the companion rather than rendering as a void.
_EMPTY_HINTS: dict[str, str] = {
    BACKLOG: "Nothing waiting.",
    REFINED: "Nothing ready to pick up.",
    IN_PROGRESS: "Nothing in flight.",
    DONE: "Nothing finished yet.",
    ARCHIVED: "Nothing tucked away.",
}


def run_board_tui(db_path: Path | None = None) -> None:
    """Launch the Textual board (blocks until the user quits)."""
    BoardApp(db_path=db_path).run()


#: Leading glyph that marks a blocked card. A blocked box already carries a red
#: border, but the marker (and the ``#blocked`` badge) are redundant signals that
#: survive the highlighted-option tint and read without colour — belt-and-braces,
#: colourblind-safe.
_BLOCKED_MARK = "⊘ "


def _mix(c1: str, c2: str, t: float) -> str:
    """Blend two ``#rrggbb`` colours, ``t`` of the way from *c1* to *c2*."""
    a = tuple(int(c1.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(c2.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(a[i] * (1 - t) + b[i] * t):02x}" for i in range(3))


def _card_box(
    card: dict,
    *,
    show_project: bool,
    colours: ChipColours = PALETTE_CHIPS,
    ident: str = p.PRIMARY,
) -> RenderableType:
    """Render one card as a bordered box for an :class:`OptionList` option.

    The box is a rounded :class:`~rich.panel.Panel` whose body stacks three
    parts: a header grid (``#id`` left, project right), the priority chip plus
    the full title (wraps to the column width, so the box grows in height), and a
    right-justified tag line. A blocked card gets a border in the ``blocked`` hue,
    keeps the leading :data:`_BLOCKED_MARK`, and its ``#blocked`` badge stands out.

    ``colours`` is the chip bundle and ``ident`` the ``#id`` mark's hue; both
    default to the canonical palette. The board passes a bundle derived from the
    active theme so the box recolours on a ``Ctrl+P`` switch.
    """
    tags = card.get("tags", [])
    blocked = BLOCKED_TAG in tags

    # Header line: #id (left) and the project (right, muted) when unfiltered.
    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row(
        Text(f"#{card['id']}", style=f"bold {ident}"),
        Text(card["project"], style="dim") if show_project else Text(""),
    )

    # Title line: leading marker (blocked) + priority chip + the wrapping title.
    title = Text()
    if blocked:
        title.append(_BLOCKED_MARK, style=f"bold {colours.blocked}")
    title.append_text(priority_chip(card["priority"], colours))
    title.append(f" {card['title']}")

    parts: list[RenderableType] = [header, title]

    # Tag line: right-justified badges, omitted when the card carries no tags.
    if tags:
        tagline = Text(justify="right")
        for i, tag in enumerate(tags):
            if i:
                tagline.append(" ")
            tagline.append_text(
                tag_badge(tag, blocked=(tag == BLOCKED_TAG), colours=colours)
            )
        parts.append(tagline)

    return Panel(
        Group(*parts),
        box=rich.box.ROUNDED,
        border_style=colours.blocked if blocked else "",
        padding=(0, 1),
    )


class BoardColumn(OptionList):
    """A status column's card list.

    Routes its navigation/action keys to the parent app so the focused list
    drives the whole board. ``up``/``down`` stay native (the option highlight);
    ``left``/``right`` are rebound onto the app's pane focus.
    """

    BINDINGS = [
        Binding("left", "app.focus_prev_col", "Col ←"),
        Binding("right", "app.focus_next_col", "Col →"),
        Binding("less_than_sign", "app.move_left", "Move ←"),
        Binding("greater_than_sign", "app.move_right", "Move →"),
        Binding("enter", "app.detail", "Detail"),
        # Number keys jump straight to a column (discoverable via the palette).
        Binding("1", "app.focus_col(0)", "Col 1", show=False),
        Binding("2", "app.focus_col(1)", "Col 2", show=False),
        Binding("3", "app.focus_col(2)", "Col 3", show=False),
        Binding("4", "app.focus_col(3)", "Col 4", show=False),
        Binding("5", "app.focus_col(4)", "Col 5", show=False),
        Binding("n", "app.new", "New"),
        Binding("e", "app.edit", "Edit"),
        Binding("C", "app.complete", "Complete"),
        Binding("c", "app.comment", "Comment"),
        Binding("t", "app.tag", "Tag"),
        Binding("b", "app.block", "Block"),
        Binding("u", "app.unblock", "Unblock"),
        Binding("p", "app.filter_project", "Project"),
        Binding("slash", "app.search", "Search"),
        Binding("d", "app.toggle_done", "Done"),
        Binding("a", "app.toggle_archived", "Archived"),
        Binding("r", "app.reload_board", "Reload"),
    ]


#: The card screen's view-mode action bindings — the set :meth:`CardScreen.check_action`
#: hides while editing (they don't apply with the form up). Save and Close are
#: deliberately absent: Save is the edit-mode action, Close is universal.
_VIEW_ACTIONS: frozenset[str] = frozenset(
    {
        "edit",
        "comment",
        "complete",
        "block",
        "unblock",
        "export",
    }
)

#: A reference value is rendered as a clickable link when it carries a URI
#: scheme (``https://``, ``file://``, …). Bare IDs like ``WIKTOR-2342`` have no
#: scheme and render as plain text.
_URI_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def _is_linkable(value: str) -> bool:
    """Whether a reference value should render as a clickable link."""
    return bool(_URI_SCHEME.match(value))


class CardScreen(ModalScreen[None]):
    """A near-fullscreen card surface with a view↔edit toggle.

    One screen, two modes. *view* is read-only — the card's fields and its
    comment thread, with comment / complete / block reachable in place. *edit*
    is the comprehensive form: title, priority, status, tags, references,
    description and acceptance, all in one place. Tags, references and status
    are a working copy applied only on **Save**, so the form is the single,
    cohesive editor and ``escape`` discards every pending change. ``e`` flips
    view→edit; **Save** (or ``ctrl+s``) persists in place and flips back to view
    (so an edit lands without a round-trip to the board); ``escape`` cancels an
    edit back to view, or closes the screen from view.

    The frame is near-fullscreen for room, but the content column stays capped
    (see ``_board.tcss``) so running prose keeps a readable measure — the win
    from the detail-readability pass.

    The screen never touches the database itself: every change posts a message
    (:class:`Saved` for the form, :class:`Mutate` for comment / complete /
    block) that the app persists, after which the app feeds the refreshed card
    back via :meth:`show_card`. Mutation stays in the service layer, mirroring
    the rest of the board.

    Block/unblock (``b``/``u``) stay view-mode gestures — they carry a reason
    comment a plain tag can't — so the form's tag editor leaves the ``blocked``
    tag alone, carrying it through a save untouched.

    The footer is contextual: :meth:`check_action` gates the bindings to the
    active mode and the card's tag state, so the binding bar advertises only what
    you can do right now.
    """

    class Saved(Message):
        """Posted when an edit is saved; carries the whole working copy.

        The form is the single place a card is changed, so a save carries every
        editable facet: ``fields`` (title/priority/description/acceptance for
        :func:`edit_card`), the target ``status``, and the full ``tags`` and
        ``references`` sets (set-replace). The app persists these via the
        service layer and refreshes the open screen — the screen deliberately
        doesn't write to the DB itself.
        """

        def __init__(
            self,
            card_id: int,
            fields: dict,
            *,
            status: str,
            tags: list[str],
            references: list[dict],
        ) -> None:
            self.card_id = card_id
            self.fields = fields
            self.status = status
            self.tags = tags
            self.references = references
            super().__init__()

    class Mutate(Message):
        """Posted to ask the app to apply an in-place action, then refresh.

        Covers the view-mode actions that stay outside the edit form — comment,
        block/unblock and complete. Like :class:`Saved`, the screen never writes
        to the DB itself: it posts the intent (with any gathered input), the app
        persists via the service layer and feeds the refreshed card back through
        :meth:`show_card`, so the action lands in place without bouncing to the
        board.

        ``op`` is the action name; ``value`` carries its payload — the comment
        body or the completion summary — and is ``None`` for block/unblock.
        """

        def __init__(self, card_id: int, op: str, value: object = None) -> None:
            self.card_id = card_id
            self.op = op
            self.value = value
            super().__init__()

    BINDINGS = [
        Binding("e", "edit", "Edit"),
        Binding("ctrl+s", "save", "Save"),
        Binding("c", "comment", "Comment"),
        Binding("C", "complete", "Complete"),
        Binding("b", "block", "Block"),
        Binding("u", "unblock", "Unblock"),
        Binding("x", "export", "Export"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(
        self,
        card: dict,
        comments: list[dict],
        *,
        mode: str = "view",
        chip_colours: ChipColours = PALETTE_CHIPS,
    ) -> None:
        super().__init__()
        self._card = card
        self._comments = comments
        self._mode = mode
        self._chip_colours = chip_colours
        # The edit form's working copy of the list-valued fields: edits stay
        # here until Save, so Cancel discards them. Re-snapshotted from the card
        # whenever the form opens (see _reset_edit_fields).
        self._edit_tags: list[str] = list(card.get("tags", []))
        self._edit_refs: list[dict] = [dict(r) for r in card.get("references", [])]

    def compose(self) -> ComposeResult:
        card = self._card
        with Vertical(id="card-dialog", classes="modal-dialog"):
            # View mode: a static title+meta header pinned above a scrolling body,
            # so you keep a reference to which card you're reading as the content
            # scrolls past. Header and body share the same capped, centred measure
            # so the title sits squarely over the content rather than flush-left.
            with Vertical(id="card-header"):
                with Vertical(id="card-header-content"):
                    yield from self._header_widgets()
            with VerticalScroll(id="card-view"):
                with Vertical(id="card-view-content"):
                    yield from self._view_widgets()
            # Edit mode: the form. Buttons sit outside the scroll so they're
            # always reachable; fields share the same capped measure.
            with Vertical(id="card-edit"):
                yield Label(f"Edit card #{card['id']}", classes="modal-title")
                with VerticalScroll(id="edit-fields"):
                    yield Label("Title", classes="field-label")
                    yield Input(value=card["title"], id="edit-title")
                    yield Label("Priority", classes="field-label")
                    yield RadioSet(
                        *(
                            RadioButton(p, value=(p == card["priority"]))
                            for p in _PRIORITIES
                        ),
                        id="edit-priority",
                    )
                    yield Label("Status", classes="field-label")
                    yield Select(
                        [(col_label(s), s) for s in _PANES],
                        value=card["status"],
                        allow_blank=False,
                        id="edit-status",
                    )
                    yield Label("Tags", classes="field-label")
                    yield Input(placeholder="add a tag…", id="edit-tag-input")
                    yield Horizontal(id="edit-tag-chips", classes="chip-row")
                    yield Label("References", classes="field-label")
                    with Horizontal(id="edit-ref-add", classes="edit-add-row"):
                        yield Input(placeholder="label", id="edit-ref-label")
                        yield Input(
                            placeholder="value (URL, file://, ID)", id="edit-ref-value"
                        )
                        yield Button("Add", id="edit-ref-add-btn")
                    yield Vertical(id="edit-ref-rows")
                    yield Label("Description", classes="field-label")
                    yield TextArea(card.get("description") or "", id="edit-description")
                    yield Label("Acceptance criteria", classes="field-label")
                    yield TextArea(
                        card.get("acceptance_criteria") or "", id="edit-acceptance"
                    )
                with Horizontal(classes="modal-buttons"):
                    yield Button("Save", id="edit-save", variant="primary")
                    yield Button("Cancel", id="edit-cancel")
            yield Footer()

    def on_mount(self) -> None:
        self._apply_mode()

    @property
    def card_id(self) -> int:
        """The id of the card currently on screen."""
        return self._card["id"]

    @property
    def is_editing(self) -> bool:
        """True while the edit form is showing — a live refresh must not clobber
        an in-progress edit, so the app skips refreshing in this state."""
        return self._mode == "edit"

    def matches(self, card: dict, comments: list[dict]) -> bool:
        """Whether the on-screen card and comments already equal *card* /
        *comments* — lets a live refresh skip a no-op re-render (which would
        otherwise reset the body's scroll position)."""
        return self._card == card and self._comments == comments

    # -- view content ------------------------------------------------------

    def _header_widgets(self) -> list[Widget]:
        """The pinned header: the wrapping title and the meta/badges line. Built
        fresh each time so a save re-renders it in place — title, status, priority
        and tags can all change on save."""
        card = self._card
        # Title wraps (a Static, not a clipping Label); priority/tags move to the
        # meta line as chips.
        return [
            Static(escape(f"#{card['id']}  {card['title']}"), classes="detail-title"),
            Static(self._meta(card), classes="detail-meta"),
        ]

    def _view_widgets(self) -> list[Widget]:
        """The scrolling body as a flat widget list (built fresh each time so a
        save can re-render the view in place). The title and meta live in the
        pinned header (:meth:`_header_widgets`), not here."""
        card = self._card
        widgets: list[Widget] = []
        for heading, body in (
            ("Description", card["description"]),
            ("Acceptance criteria", card["acceptance_criteria"]),
            ("Completion summary", card["completion_summary"]),
        ):
            if body:
                widgets.append(Static(heading, classes="section-head"))
                widgets.append(Rule())
                # Markdown, not Static(escape(...)): plain text is valid markdown,
                # so both render seamlessly with no format flag. The parser also
                # makes "[...]" inert (only "[label](url)" is a link), so the
                # markup-injection escape() the other sections need isn't required
                # here. Links render-only (open_links=False) — References stays the
                # canonical link surface.
                widgets.append(
                    Markdown(body, parser_factory=md_parser, open_links=False)
                )
        references = card.get("references", [])
        if references:
            widgets.append(
                Static(f"References ({len(references)})", classes="section-head")
            )
            widgets.append(Rule())
            for position, ref in enumerate(references, 1):
                widgets.append(Static(self._reference_line(position, ref)))
        widgets.append(
            Static(f"Comments ({len(self._comments)})", classes="section-head")
        )
        widgets.append(Rule())
        if self._comments:
            for comment in self._comments:
                # Each comment is its own block; escape the body so brackets
                # aren't parsed as markup (Textual 8's Content system parses
                # "[...]").
                widgets.append(
                    Vertical(
                        Static(self._comment_head(comment), classes="comment-head"),
                        Static(escape(comment["body"])),
                        classes="comment",
                    )
                )
        else:
            widgets.append(Static("(none)", classes="detail-dim"))
        return widgets

    # -- mode handling -----------------------------------------------------

    def _apply_mode(self) -> None:
        """Show the active mode's container; focus the title when editing.

        Re-runs :meth:`refresh_bindings` so the footer tracks the mode flip —
        the view actions drop out in edit mode, Save appears.
        """
        self.query_one("#card-header").display = self._mode == "view"
        self.query_one("#card-view").display = self._mode == "view"
        self.query_one("#card-edit").display = self._mode == "edit"
        if self._mode == "edit":
            self.query_one("#edit-title", Input).focus()
        self.refresh_bindings()

    async def action_edit(self) -> None:
        """``e`` in view mode opens the form (no-op while already editing)."""
        if self._mode == "view":
            await self._reset_edit_fields()
            self._mode = "edit"
            self._apply_mode()

    def action_save(self) -> None:
        """``ctrl+s`` in edit mode persists the form (mirrors the Save button)."""
        if self._mode == "edit":
            self._submit()

    def action_close(self) -> None:
        """Esc backs an edit out to view first, then closes from view."""
        if self._mode == "edit":
            self._mode = "view"
            self._apply_mode()
        else:
            self.dismiss(None)

    # -- in-place actions (view mode only) ---------------------------------
    #
    # Each posts a Mutate the app applies and reflects back via show_card; none
    # touches the DB directly, mirroring the Saved round-trip. All are inert
    # outside view mode so edit-mode keystrokes stay with the form (check_action
    # also hides them from the footer there).

    @work
    async def action_comment(self) -> None:
        if self._mode != "view":
            return
        body = await self.app.push_screen_wait(CommentScreen(self._card["id"]))
        if body:
            self.post_message(self.Mutate(self._card["id"], "comment", body))

    @work
    async def action_complete(self) -> None:
        if self._mode != "view":
            return
        summary = await self.app.push_screen_wait(CompleteScreen(self._card["id"]))
        if summary:
            self.post_message(self.Mutate(self._card["id"], "complete", summary))

    @work
    async def action_export(self) -> None:
        """``x`` in view mode prompts for a destination — pre-filled with
        ``card-N.md`` in the cwd — and writes the card's markdown there,
        rendered through the same export layer as the CLI."""
        if self._mode != "view":
            return
        suggestion = Path.cwd() / f"card-{self._card['id']}.md"
        raw = await self.app.push_screen_wait(
            ExportScreen(self._card["id"], suggestion)
        )
        if not raw:
            return
        card = dict(self._card)
        card["comments"] = self._comments
        path = Path(raw).expanduser()
        try:
            path.write_text(export.card_markdown(card) + "\n", encoding="utf-8")
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            return
        self.notify(f"Exported to {path}")

    def action_block(self) -> None:
        if self._mode == "view":
            self.post_message(self.Mutate(self._card["id"], "block"))

    def action_unblock(self) -> None:
        if self._mode == "view":
            self.post_message(self.Mutate(self._card["id"], "unblock"))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Gate the footer/bindings to the active mode and card state.

        Edit mode exposes only Save + Close — the view actions don't apply with
        the form up (tags, references and status are edited *in* the form now).
        View mode hides Save and shows whichever of block / unblock matches the
        card's current tag (they're mutually exclusive). Paired with
        :meth:`refresh_bindings` so the footer updates on every mode flip and
        in-place change.
        """
        editing = self._mode == "edit"
        if action == "save":
            return editing
        if action in _VIEW_ACTIONS:
            if editing:
                return False
            if action == "block":
                return BLOCKED_TAG not in self._card.get("tags", [])
            if action == "unblock":
                return BLOCKED_TAG in self._card.get("tags", [])
        return True

    async def show_card(self, card: dict, comments: list[dict]) -> None:
        """Re-render with a freshly-saved card and return to view mode.

        Called by the app after it persists a :class:`Saved`, so the edit lands
        visibly without bouncing back to the board.
        """
        self._card = card
        self._comments = comments
        header = self.query_one("#card-header-content", Vertical)
        await header.remove_children()
        await header.mount(*self._header_widgets())
        content = self.query_one("#card-view-content", Vertical)
        await content.remove_children()
        await content.mount(*self._view_widgets())
        await self._reset_edit_fields()
        self._mode = "view"
        self._apply_mode()

    # -- edit form ---------------------------------------------------------

    async def _reset_edit_fields(self) -> None:
        """Sync the form widgets to the current card, re-snapshotting the tag
        and reference working copies (covers a re-open after a save changed the
        values, and discards any uncommitted edits on the next open)."""
        card = self._card
        self.query_one("#edit-title", Input).value = card["title"]
        radio = self.query_one("#edit-priority", RadioSet)
        for index, button in enumerate(radio.query(RadioButton)):
            if _PRIORITIES[index] == card["priority"]:
                button.value = True  # RadioSet unsets the others
        self.query_one("#edit-status", Select).value = card["status"]
        self.query_one("#edit-description", TextArea).text = (
            card.get("description") or ""
        )
        self.query_one("#edit-acceptance", TextArea).text = (
            card.get("acceptance_criteria") or ""
        )
        self._edit_tags = list(card.get("tags", []))
        self._edit_refs = [dict(r) for r in card.get("references", [])]
        self.query_one("#edit-tag-input", Input).value = ""
        self.query_one("#edit-ref-label", Input).value = ""
        self.query_one("#edit-ref-value", Input).value = ""
        await self._render_tag_chips()
        await self._render_ref_rows()

    async def _render_tag_chips(self) -> None:
        """Re-render the working-copy tag chips, one removable ``✕ tag`` button
        each. ``blocked`` is deliberately not shown — it's carried through a save
        untouched and stays driven by ``b``/``u`` (see the class docstring)."""
        row = self.query_one("#edit-tag-chips", Horizontal)
        await row.remove_children()
        chips = [
            Button(f"✕ {tag}", id=f"edit-tag-rm-{i}", classes="tag-remove")
            for i, tag in enumerate(self._edit_tags)
            if tag != BLOCKED_TAG
        ]
        if chips:
            await row.mount(*chips)

    async def _render_ref_rows(self) -> None:
        """Re-render the working-copy reference rows, one removable
        ``✕ label: value`` button each (stacked, like the old RefScreen)."""
        rows = self.query_one("#edit-ref-rows", Vertical)
        await rows.remove_children()
        widgets = [
            Button(
                f"✕ {ref['label']}: {ref['value']}",
                id=f"edit-ref-rm-{i}",
                classes="tag-remove",
            )
            for i, ref in enumerate(self._edit_refs)
        ]
        if widgets:
            await rows.mount(*widgets)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "edit-save":
            self._submit()
        elif bid == "edit-cancel":
            self.action_close()
        elif bid == "edit-ref-add-btn":
            await self._add_ref_from_inputs()
        elif bid.startswith("edit-tag-rm-"):
            await self._remove_tag(int(bid.rsplit("-", 1)[1]))
        elif bid.startswith("edit-ref-rm-"):
            await self._remove_ref(int(bid.rsplit("-", 1)[1]))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the tag input adds a tag; Enter in the ref value adds the
        reference — quick keyboard paths that mirror the buttons."""
        if event.input.id == "edit-tag-input":
            await self._add_tag_from_input()
        elif event.input.id == "edit-ref-value":
            await self._add_ref_from_inputs()

    async def _add_tag_from_input(self) -> None:
        field = self.query_one("#edit-tag-input", Input)
        tag = field.value.strip()
        if not tag:
            return
        if tag == BLOCKED_TAG:
            # blocked is a status-like flag owned by b/u, not a free tag.
            self.notify("Use b / u to block or unblock", severity="warning")
            return
        if tag in self._edit_tags:
            field.value = ""
            return
        self._edit_tags.append(tag)
        field.value = ""
        await self._render_tag_chips()

    async def _remove_tag(self, index: int) -> None:
        if 0 <= index < len(self._edit_tags):
            del self._edit_tags[index]
            await self._render_tag_chips()

    async def _add_ref_from_inputs(self) -> None:
        label = self.query_one("#edit-ref-label", Input).value.strip()
        value = self.query_one("#edit-ref-value", Input).value.strip()
        if not label or not value:
            return  # both halves are required
        self._edit_refs.append({"label": label, "value": value})
        self.query_one("#edit-ref-label", Input).value = ""
        self.query_one("#edit-ref-value", Input).value = ""
        await self._render_ref_rows()

    async def _remove_ref(self, index: int) -> None:
        if 0 <= index < len(self._edit_refs):
            del self._edit_refs[index]
            await self._render_ref_rows()

    def _submit(self) -> None:
        title = self.query_one("#edit-title", Input).value.strip()
        if not title:
            return  # title required; stay in the form
        idx = self.query_one("#edit-priority", RadioSet).pressed_index
        priority = _PRIORITIES[idx] if idx >= 0 else self._card["priority"]
        status_val = self.query_one("#edit-status", Select).value
        status = status_val if isinstance(status_val, str) else self._card["status"]
        # Don't dismiss: the app persists this, then calls show_card() to flip
        # us back to view with the saved values. Status comes from the Select;
        # tags/references come from the working copy the form maintains.
        self.post_message(
            self.Saved(
                self._card["id"],
                {
                    "title": title,
                    "priority": priority,
                    "description": self.query_one("#edit-description", TextArea).text,
                    "acceptance_criteria": self.query_one(
                        "#edit-acceptance", TextArea
                    ).text,
                },
                status=status,
                tags=list(self._edit_tags),
                references=[dict(r) for r in self._edit_refs],
            )
        )

    def set_chip_colours(self, colours: ChipColours) -> None:
        """Re-colour the chips to a new theme's palette, live.

        The only chip-bearing surface on this screen is the meta line, so a
        theme switch just needs that one ``Static`` re-rendered &mdash; cheap and
        synchronous (no re-mount). Called by the app from its theme-change hook.
        """
        self._chip_colours = colours
        if self.is_mounted:
            self.query_one(".detail-meta", Static).update(self._meta(self._card))

    def _meta(self, card: dict) -> Text:
        """One line of fields, each set off by the same dim middot:
        ``project · status · priority · #tag #tag``.

        The uniform separator gives priority and the tags the same rhythm as
        project/status, instead of trailing off space-separated. Tags read as
        one group (the last field), so the middot sits before the group, not
        between every badge.
        """
        sep = "  ·  "
        meta = Text()
        meta.append(card["project"], style="dim")
        meta.append(sep, style="dim")
        meta.append(col_label(card["status"]))
        meta.append(sep, style="dim")
        meta.append_text(priority_chip(card["priority"], self._chip_colours))
        tags = card.get("tags", [])
        if tags:
            meta.append(sep, style="dim")
            for i, tag in enumerate(tags):
                if i:
                    meta.append(" ")
                meta.append_text(
                    tag_badge(
                        tag, blocked=(tag == BLOCKED_TAG), colours=self._chip_colours
                    )
                )
        return meta

    @staticmethod
    def _reference_line(position: int, ref: dict) -> Text:
        """A ``N. label: value`` line; the value is a clickable link if it
        carries a URI scheme, otherwise plain text."""
        line = Text()
        line.append(f"{position}. ", style="dim")
        line.append(f"{ref['label']}: ", style="bold")
        value = ref["value"]
        line.append(value, style=f"link {value}" if _is_linkable(value) else "")
        return line

    @staticmethod
    def _comment_head(comment: dict) -> Text:
        head = Text(comment["author"], style="dim")
        created = comment.get("created_at")
        if created:
            # Trim the stored ISO timestamp to a readable "YYYY-MM-DD HH:MM".
            head.append(f"  ·  {created[:16].replace('T', ' ')}", style="dim")
        return head


class CommentScreen(ModalScreen[str | None]):
    """A single-line comment input; resolves to the body, or ``None`` on cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int) -> None:
        super().__init__()
        self._card_id = card_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"Comment on card #{self._card_id}", classes="modal-title")
            yield Input(placeholder="Your comment…", id="comment-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", id="comment-add", variant="primary")
                yield Button("Cancel", id="comment-cancel")

    def on_mount(self) -> None:
        self.query_one("#comment-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "comment-add":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        body = self.query_one("#comment-input", Input).value.strip()
        self.dismiss(body or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ExportScreen(ModalScreen[str | None]):
    """Prompt for an export destination; resolves to the path, or ``None`` on
    cancel. Pre-populated with a suggested path so Enter accepts the default;
    the value is free to edit (``~`` is expanded by the caller)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int, suggestion: Path) -> None:
        super().__init__()
        self._card_id = card_id
        self._suggestion = suggestion

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"Export card #{self._card_id} to…", classes="modal-title")
            yield Input(value=str(self._suggestion), id="export-path")
            with Horizontal(classes="modal-buttons"):
                yield Button("Export", id="export-save", variant="primary")
                yield Button("Cancel", id="export-cancel")

    def on_mount(self) -> None:
        self.query_one("#export-path", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-save":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        path = self.query_one("#export-path", Input).value.strip()
        self.dismiss(path or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TagScreen(ModalScreen[str | None]):
    """Add a tag, or pick a current tag to remove.

    Resolves to a single tag (or ``None`` on cancel) which the app *toggles*:
    a tag absent from the card is added, one already present is removed. Typing
    a name and applying toggles it; the current-tag chips give removal an
    explicit, discoverable path (click a chip → that tag toggles off).
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int, tags: list[str] | None = None) -> None:
        super().__init__()
        self._card_id = card_id
        self._tags = tags or []

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(f"Tag card #{self._card_id}", classes="modal-title")
            yield Input(placeholder="add a tag…", id="tag-input")
            if self._tags:
                yield Label("Current tags (select to remove):", classes="field-label")
                with Horizontal(id="tag-current"):
                    for idx, tag in enumerate(self._tags):
                        yield Button(
                            f"✕ {tag}", id=f"tag-rm-{idx}", classes="tag-remove"
                        )
            with Horizontal(classes="modal-buttons"):
                yield Button("Apply", id="tag-apply", variant="primary")
                yield Button("Cancel", id="tag-cancel")

    def on_mount(self) -> None:
        self.query_one("#tag-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "tag-apply":
            self._submit()
        elif button_id.startswith("tag-rm-"):
            # A current-tag chip: return that tag so the app toggles it off.
            self.dismiss(self._tags[int(button_id.removeprefix("tag-rm-"))])
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        tag = self.query_one("#tag-input", Input).value.strip()
        self.dismiss(tag or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SearchScreen(ModalScreen[str | None]):
    """Capture a title-search query for the board.

    Resolves to the typed query (possibly ``""`` to clear an active filter), or
    ``None`` on escape/cancel — which leaves the current filter untouched. The
    input is pre-filled with the active query so editing or clearing it is one
    gesture.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current: str | None = None) -> None:
        super().__init__()
        self._current = current or ""

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("Search cards by title", classes="modal-title")
            yield Input(
                value=self._current,
                placeholder="title contains…  (empty to clear)",
                id="search-input",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Search", id="search-apply", variant="primary")
                yield Button("Cancel", id="search-cancel")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if (event.button.id or "") == "search-apply":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        # Empty is a meaningful result (clear the filter), distinct from the
        # ``None`` that escape/cancel returns, so dismiss the raw stripped value.
        self.dismiss(self.query_one("#search-input", Input).value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class ProjectFilterScreen(ModalScreen[object | None]):
    """Pick the project to filter the board by, via a ``Select`` dropdown.

    Resolves to one of three outcomes, kept distinct so "all" never collapses
    into the cancel ``None``:

    * a project name — filter to that project;
    * :data:`_ALL_PROJECTS` — clear the filter (show every project);
    * ``None`` — escape/cancel, leave the active filter untouched.

    The dropdown auto-expands and applies on selection (no Apply button): the
    chosen value dismisses the modal straight away. The one wrinkle is that
    ``Select`` posts a :class:`Select.Changed` for its *initial* value on mount,
    which would dismiss instantly — so a change back to the value we opened with
    (the mount echo, and equally a no-op re-pick) is ignored.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, projects: list[str], current: str | None = None) -> None:
        super().__init__()
        self._projects = projects
        self._initial: object = _ALL_PROJECTS if current is None else current

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("Filter by project", classes="modal-title")
            yield Select(
                [
                    ("All projects", _ALL_PROJECTS),
                    *((proj, proj) for proj in self._projects),
                ],
                value=self._initial,
                allow_blank=False,
                id="project-select",
            )

    def on_mount(self) -> None:
        select = self.query_one("#project-select", Select)
        select.focus()
        select.expanded = True  # open the dropdown so picking is one gesture

    def on_select_changed(self, event: Select.Changed) -> None:
        # ``Select`` echoes its initial value as a Changed on mount; ignore that
        # (and a no-op re-pick of the same value) — only a real change applies.
        if event.value == self._initial:
            return
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


#: Priority choices, low→high, as offered in the new/edit modals.
_PRIORITIES: tuple[str, ...] = ("low", "medium", "high")


class NewCardScreen(ModalScreen[dict | None]):
    """Capture a new card's title, project and priority.

    Resolves to a ``{title, project, priority}`` dict, or ``None`` on cancel.
    An empty title keeps the modal open (a titleless card is never created);
    escape always cancels.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, default_project: str) -> None:
        super().__init__()
        self._default_project = default_project

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label("New card", classes="modal-title")
            yield Input(placeholder="Title…", id="new-title")
            yield Input(
                value=self._default_project, placeholder="project", id="new-project"
            )
            yield RadioSet(
                *(RadioButton(p, value=(p == "medium")) for p in _PRIORITIES),
                id="new-priority",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", id="new-add", variant="primary")
                yield Button("Cancel", id="new-cancel")

    def on_mount(self) -> None:
        self.query_one("#new-title", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-add":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        title = self.query_one("#new-title", Input).value.strip()
        if not title:
            return  # title required; stay open (escape to cancel)
        project = (
            self.query_one("#new-project", Input).value.strip() or self._default_project
        )
        idx = self.query_one("#new-priority", RadioSet).pressed_index
        priority = _PRIORITIES[idx] if idx >= 0 else "medium"
        self.dismiss({"title": title, "project": project, "priority": priority})

    def action_cancel(self) -> None:
        self.dismiss(None)


class CompleteScreen(ModalScreen[str | None]):
    """Prompt for a completion summary; resolves to the summary or ``None``.

    A summary is the whole point of this gesture (vs a bare move into done), so
    an empty summary cancels — done cards are never summary-less.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, card_id: int) -> None:
        super().__init__()
        self._card_id = card_id

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Label(
                f"Complete card #{self._card_id} — summary", classes="modal-title"
            )
            yield Input(placeholder="What was done…", id="complete-input")
            with Horizontal(classes="modal-buttons"):
                yield Button("Complete", id="complete-ok", variant="primary")
                yield Button("Cancel", id="complete-cancel")

    def on_mount(self) -> None:
        self.query_one("#complete-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "complete-ok":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        summary = self.query_one("#complete-input", Input).value.strip()
        self.dismiss(summary or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BoardApp(MaitApp):
    """Full-screen kanban over every project's cards."""

    TITLE = "mait-code board"
    CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_board.tcss"]

    #: How often (seconds) to poll for external edits. `PRAGMA data_version`
    #: is a header read, not a query, so a tight interval stays cheap.
    _REFRESH_INTERVAL = 1.0

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._conn = get_connection(db_path)  # one connection for the app's life
        self._project_filter: str | None = None  # None == all projects
        self._search: str | None = None  # None == no title filter
        self._projects: list[str] = []
        self._show_done = False  # Done is hidden by default to widen the flow
        self._show_archived = False
        self._focused_col = 0
        self._card_status: dict[int, str] = {}
        self._data_version = 0  # last-seen PRAGMA data_version (set on mount)

    def compose(self) -> ComposeResult:
        yield BrandBanner(subtitle="Board")
        with Horizontal(id="body"):
            for status in _PANES:
                with Vertical(classes="col", id=f"col-{status}"):
                    yield Label(
                        col_label(status), classes="col-head", id=f"head-{status}"
                    )
                    yield BoardColumn(id=f"tbl-{status}")
        yield Footer()

    def on_mount(self) -> None:
        self._projects = service.list_projects(self._conn)
        # Done and archived stay hidden until their toggles (`d` / `a`) reveal them.
        self.query_one("#col-done", Vertical).display = False
        self.query_one("#col-archived", Vertical).display = False
        # Re-render the chip-bearing surfaces whenever the theme changes, so a
        # Ctrl+P switch recolours the Rich-text chips (which can't read $-vars).
        self.theme_changed_signal.subscribe(self, self._on_theme_change)
        self._update_subtitle()
        self._reload()
        self._focus_current()
        # Live refresh: poll for commits from other connections (the `mait-code`
        # CLI, skills) and reload underneath the user so they don't need `r`.
        self._data_version = self._read_data_version()
        self.set_interval(self._REFRESH_INTERVAL, self._poll_external_changes)

    def on_unmount(self) -> None:
        super().on_unmount()  # persists the active theme (MaitApp)
        self._conn.close()

    # -- theming -----------------------------------------------------------

    def _chip_colours(self, theme: Theme | None = None) -> ChipColours:
        """The chip palette for the active (or given) theme.

        Tags take the theme's *secondary* hue so they read distinct from the
        primary frame/#id; the heat scale and blocked marker take the semantic
        roles. ``secondary`` can be unset on a stray built-in theme, so it falls
        back to ``primary``.
        """
        t = theme or self.current_theme
        # The ANSI passthrough themes set their colours to named tokens
        # ("ansi_blue", "ansi_default") rather than hex. Those are valid in CSS
        # (Textual maps them to the terminal palette), but *not* as Rich-text
        # styles: Textual re-parses them when the card screen's Static paints and
        # raises MissingStyle. So for any non-hex theme, fall back to the
        # canonical hex palette for the chips — the CSS chrome still follows the
        # active theme. `primary` is the canary (themes don't mix hex and named).
        if not (t.primary or "").startswith("#"):
            return PALETTE_CHIPS
        # Each role but `primary` is optional, so coalesce to primary when unset.
        # `low` recedes to a muted grey (foreground blended toward the background)
        # as the quiet end of the heat scale, distinct from the secondary tags.
        return ChipColours(
            high=t.error or t.primary,
            medium=t.warning or t.primary,
            low=_mix(t.foreground or p.FOREGROUND, t.background or p.BACKGROUND, 0.45),
            tag=t.secondary or t.primary,
            blocked=t.error or t.primary,
        )

    def _on_theme_change(self, theme: Theme) -> None:
        """Repaint chips on a theme switch (board columns + any open card)."""
        self._reload()
        if isinstance(self.screen, CardScreen):
            self.screen.set_chip_colours(self._chip_colours(theme))

    # -- layout helpers ----------------------------------------------------

    def _visible_statuses(self) -> list[str]:
        statuses = [BACKLOG, REFINED, IN_PROGRESS]
        if self._show_done:
            statuses.append(DONE)
        if self._show_archived:
            statuses.append(ARCHIVED)
        return statuses

    def _update_subtitle(self) -> None:
        # The live filter/search state rides the banner's view-name line; the
        # `p`/`/` key hints it used to carry are already in the footer.
        parts = [f"Board · project: {self._project_filter or 'all'}"]
        if self._search:
            parts.append(f"search: {self._search!r}")
        self.query_one(BrandBanner).set_subtitle("  ".join(parts))

    def _reload(self) -> None:
        """Re-query with the active filter and repaint every pane."""
        cards = service.list_cards(
            self._conn,
            project=self._project_filter,
            include_archived=self._show_archived,
            search=self._search,
        )
        self._card_status = {c["id"]: c["status"] for c in cards}
        by_status: dict[str, list[dict]] = {}
        for card in cards:
            by_status.setdefault(card["status"], []).append(card)
        show_project = self._project_filter is None
        colours = self._chip_colours()
        # #id uses the theme primary, but falls back to hex under a non-hex
        # (ANSI) theme to match the chip bundle and stay a valid Rich style.
        primary = self.current_theme.primary
        ident = primary if (primary or "").startswith("#") else p.PRIMARY
        for status in _PANES:
            column = self.query_one(f"#tbl-{status}", BoardColumn)
            column.clear_options()
            group = by_status.get(status, [])
            column.add_options(
                Option(
                    _card_box(
                        card,
                        show_project=show_project,
                        colours=colours,
                        ident=ident,
                    ),
                    id=str(card["id"]),
                )
                for card in group
            )
            if not group:
                column.add_option(
                    Option(
                        Text(empty_state(_EMPTY_HINTS[status]), style="dim"),
                        disabled=True,
                    )
                )
            head = self.query_one(f"#head-{status}", Label)
            head.update(f"{col_label(status)} ({len(group)})")

    def _focus_current(self) -> None:
        status = self._visible_statuses()[self._focused_col]
        column = self.query_one(f"#tbl-{status}", BoardColumn)
        # OptionList doesn't auto-highlight on focus (unlike a DataTable cursor),
        # so default to the first card — otherwise actions have nothing selected.
        # An empty column holds only its disabled companion hint, which must
        # never be highlighted (it carries no card id).
        if (
            column.highlighted is None
            and column.option_count
            and not column.get_option_at_index(0).disabled
        ):
            column.highlighted = 0
        column.focus()

    def _focus_status(self, status: str) -> None:
        """Focus the pane for *status* (used by tests and card-following)."""
        statuses = self._visible_statuses()
        self._focused_col = statuses.index(status)
        self._focus_current()

    def _selected_card_id(self) -> int | None:
        status = self._visible_statuses()[self._focused_col]
        column = self.query_one(f"#tbl-{status}", BoardColumn)
        if column.highlighted is None:  # empty column
            return None
        option = column.get_option_at_index(column.highlighted)
        return int(option.id) if option.id is not None else None

    def _select_card(self, card_id: int) -> bool:
        """Follow a card to its (possibly new) pane and highlight it.

        Returns ``True`` if the card was found in a visible pane and selected,
        ``False`` if it's gone, archived out of view, or filtered out — letting
        callers fall back to a sensible default focus.
        """
        status = self._card_status.get(card_id)
        statuses = self._visible_statuses()
        if status is None or status not in statuses:
            return False
        self._focused_col = statuses.index(status)
        column = self.query_one(f"#tbl-{status}", BoardColumn)
        try:
            column.highlighted = column.get_option_index(str(card_id))
        except OptionDoesNotExist:
            return False
        column.focus()
        return True

    # -- navigation --------------------------------------------------------

    def get_system_commands(self, screen: Screen):
        """Expose the board's actions in the Ctrl+P command palette."""
        yield from super().get_system_commands(screen)
        yield SystemCommand("New card", "Create a card in backlog", self.action_new)
        yield SystemCommand("Edit card", "Edit the focused card", self.action_edit)
        yield SystemCommand(
            "Complete card",
            "Complete the focused card with a summary",
            self.action_complete,
        )
        yield SystemCommand(
            "Toggle Done",
            "Show or hide the Done column",
            self.action_toggle_done,
        )
        yield SystemCommand(
            "Toggle archived",
            "Show or hide the archived pane",
            self.action_toggle_archived,
        )
        yield SystemCommand(
            "Change project filter",
            "Filter cards by project",
            self.action_filter_project,
        )
        yield SystemCommand(
            "Search cards",
            "Filter cards by a title substring",
            self.action_search,
        )
        yield SystemCommand(
            "Reload board", "Re-read the board from disk", self.action_reload_board
        )
        for idx, status in enumerate(BOARD_ORDER):
            yield SystemCommand(
                f"Jump to {col_label(status)}",
                "Focus this column",
                partial(self._jump_to, idx),
            )

    def _jump_to(self, index: int) -> None:
        statuses = self._visible_statuses()
        if 0 <= index < len(statuses):
            self._focused_col = index
            self._focus_current()

    def action_focus_col(self, index: int) -> None:
        self._jump_to(index)

    def action_focus_prev_col(self) -> None:
        n = len(self._visible_statuses())
        self._focused_col = (self._focused_col - 1) % n
        self._focus_current()

    def action_focus_next_col(self) -> None:
        n = len(self._visible_statuses())
        self._focused_col = (self._focused_col + 1) % n
        self._focus_current()

    # -- moving ------------------------------------------------------------

    def action_move_left(self) -> None:
        self._shift(-1)

    def action_move_right(self) -> None:
        self._shift(1)

    def _move_target(self, status: str, delta: int) -> str | None:
        """The status ``delta`` steps along the flow, or ``None`` (with a notify)
        when the card is off-flow or already at an end.

        Shared by the board-level move (``_shift``) and the in-place card move so
        both honour the same bounds and messaging.
        """
        if status not in _MOVE_FLOW:
            self.notify("Archived cards aren't on the move line.")
            return None
        idx = _MOVE_FLOW.index(status) + delta
        if idx < 0 or idx >= len(_MOVE_FLOW):
            self.notify("Already at the end of the flow.")
            return None
        return _MOVE_FLOW[idx]

    def _shift(self, delta: int) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        new_status = self._move_target(self._card_status.get(card_id, ""), delta)
        if new_status is None:
            return
        service.move_card(self._conn, card_id, new_status)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Card #{card_id} → {col_label(new_status)}")

    # -- block / unblock ---------------------------------------------------

    def action_block(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        service.block_card(self._conn, card_id)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Card #{card_id} blocked", severity="warning")

    def action_unblock(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        service.unblock_card(self._conn, card_id)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Card #{card_id} unblocked")

    # -- filter / archived / reload ---------------------------------------

    @work
    async def action_filter_project(self) -> None:
        # Refresh the project list first, so a project added this session shows.
        self._projects = service.list_projects(self._conn)
        result = await self.push_screen_wait(
            ProjectFilterScreen(self._projects, self._project_filter)
        )
        if result is None:
            return  # escape/cancel — leave the active filter as-is
        # A project name filters to it; the _ALL_PROJECTS sentinel clears it.
        self._project_filter = result if isinstance(result, str) else None
        self._update_subtitle()
        self._reload()
        self._focus_current()

    @work
    async def action_search(self) -> None:
        result = await self.push_screen_wait(SearchScreen(self._search))
        if result is None:
            return  # escape/cancel — leave the active filter as-is
        self._search = result or None  # empty query clears the filter
        self._update_subtitle()
        self._reload()
        self._focus_current()

    def action_toggle_done(self) -> None:
        self._show_done = not self._show_done
        self.query_one("#col-done", Vertical).display = self._show_done
        # If a now-hidden pane was focused, fall back to the last visible one.
        self._focused_col = min(self._focused_col, len(self._visible_statuses()) - 1)
        self._reload()
        self._focus_current()

    def action_toggle_archived(self) -> None:
        self._show_archived = not self._show_archived
        self.query_one("#col-archived", Vertical).display = self._show_archived
        # If a now-hidden pane was focused, fall back to the last visible one.
        self._focused_col = min(self._focused_col, len(self._visible_statuses()) - 1)
        self._reload()
        self._focus_current()

    def action_reload_board(self) -> None:
        self._projects = service.list_projects(self._conn)
        self._reload()
        self._focus_current()
        # Re-baseline so the next poll doesn't double-reload on edits we just read.
        self._data_version = self._read_data_version()

    def _read_data_version(self) -> int:
        """The SQLite ``data_version`` for this connection.

        In WAL mode it changes only when *another* connection commits, so the
        board's own mutations (made on ``self._conn``) never bump it — we only
        react to external edits from the CLI or skills.
        """
        row = self._conn.execute("PRAGMA data_version").fetchone()
        return int(row[0]) if row else 0

    async def _poll_external_changes(self) -> None:
        """Reload if another connection has committed since the last poll.

        Selection and focus are preserved so a refresh underneath the user is
        unobtrusive. When a card-detail view is open it's refreshed in place so
        it doesn't go stale (e.g. an external complete); other modals are left
        alone, with the board reloaded behind them. Focus is never stolen out
        from under a modal's cursor.
        """
        version = self._read_data_version()
        if version == self._data_version:
            return
        self._data_version = version
        self._projects = service.list_projects(self._conn)
        screen = self.screen
        on_board = len(self.screen_stack) == 1
        # Capture the selection *before* the reload clears the columns' highlight.
        selected = self._selected_card_id() if on_board else None
        self._reload()
        if isinstance(screen, CardScreen):
            await self._refresh_open_card(screen)
        elif on_board and not (selected is not None and self._select_card(selected)):
            self._focus_current()

    async def _refresh_open_card(self, screen: CardScreen) -> None:
        """Re-render an open card-detail view from the latest stored state.

        Skips edit mode (refreshing would discard an in-progress edit) and
        skips a no-op render when nothing about the card changed (preserving
        the reader's scroll position). If the card was deleted elsewhere, the
        stale view is left until the user closes it.
        """
        if screen.is_editing:
            return
        card = service.get_card(self._conn, screen.card_id)
        if card is None:
            return
        comments = service.get_comments(self._conn, screen.card_id)
        if screen.matches(card, comments):
            return
        await screen.show_card(card, comments)

    # -- detail / comment --------------------------------------------------

    @work
    async def action_detail(self) -> None:
        await self._open_card("view")

    async def _open_card(self, mode: str) -> None:
        """Open the focused card in the unified view/edit screen.

        Stays open across an in-place save (handled by ``on_card_screen_saved``);
        on close, re-reads the board and refollows the (possibly edited) card.
        """
        card_id = self._selected_card_id()
        if card_id is None:
            return
        card = service.get_card(self._conn, card_id)
        if card is None:
            return
        comments = service.get_comments(self._conn, card_id)
        await self.push_screen_wait(
            CardScreen(card, comments, mode=mode, chip_colours=self._chip_colours())
        )
        self._reload()
        self._select_card(card_id)

    async def on_card_screen_saved(self, message: CardScreen.Saved) -> None:
        """Persist an in-place edit, then refresh the still-open card screen.

        Applies the whole working copy: the text fields via ``edit_card``, then
        the set-replace of tags and references, then a status move *only* if it
        actually changed — so the done-invariant is maintained by ``move_card``
        without re-stamping ``completed_at`` on an unchanged status.
        """
        existing = service.get_card(self._conn, message.card_id)
        if existing is None:
            return
        service.edit_card(self._conn, message.card_id, **message.fields)
        service.set_tags(self._conn, message.card_id, message.tags)
        service.set_references(self._conn, message.card_id, message.references)
        if message.status != existing["status"]:
            service.move_card(self._conn, message.card_id, message.status)
        self._reload()
        card = service.get_card(self._conn, message.card_id)
        comments = service.get_comments(self._conn, message.card_id)
        if card is not None and isinstance(self.screen, CardScreen):
            await self.screen.show_card(card, comments)
        self.notify(f"Updated card #{message.card_id}")

    async def on_card_screen_mutate(self, message: CardScreen.Mutate) -> None:
        """Apply an in-place card action, then refresh the open card screen.

        The card-screen counterpart to the board-level action handlers: the same
        service calls, but the result lands back in the still-open screen (via
        :meth:`CardScreen.show_card`) instead of bouncing to the board. The board
        is reloaded too, so it's correct underneath when the screen closes.
        """
        cid = message.card_id
        card = service.get_card(self._conn, cid)
        if card is None:
            return
        op = message.op
        if op == "comment":
            service.add_comment(self._conn, cid, str(message.value))
        elif op == "block":
            service.block_card(self._conn, cid)
            self.notify(f"Card #{cid} blocked", severity="warning")
        elif op == "unblock":
            service.unblock_card(self._conn, cid)
            self.notify(f"Card #{cid} unblocked")
        elif op == "complete":
            service.complete_card(self._conn, cid, summary=str(message.value))
            self.notify(f"Card #{cid} completed")
        self._reload()
        refreshed = service.get_card(self._conn, cid)
        comments = service.get_comments(self._conn, cid)
        if refreshed is not None and isinstance(self.screen, CardScreen):
            await self.screen.show_card(refreshed, comments)

    @work
    async def action_comment(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        body = await self.push_screen_wait(CommentScreen(card_id))
        if not body:
            return
        service.add_comment(self._conn, card_id, body)
        self._reload()
        self._select_card(card_id)

    @work
    async def action_tag(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        current = service.list_tags(self._conn, card_id)
        tag = await self.push_screen_wait(TagScreen(card_id, current))
        if not tag:
            return
        # Toggle: a tag already on the card is removed, otherwise added.
        if tag in service.list_tags(self._conn, card_id):
            service.remove_tag(self._conn, card_id, tag)
            self.notify(f"Removed #{tag} from card #{card_id}")
        else:
            service.add_tag(self._conn, card_id, tag)
            self.notify(f"Tagged card #{card_id} #{tag}")
        self._reload()
        self._select_card(card_id)

    # -- mutation modals ---------------------------------------------------

    @work
    async def action_new(self) -> None:
        default = self._project_filter or get_project()
        result = await self.push_screen_wait(NewCardScreen(default))
        if not result:
            return
        card_id = service.add_card(
            self._conn,
            project=result["project"],
            title=result["title"],
            priority=result["priority"],
        )
        self._projects = service.list_projects(self._conn)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Created card #{card_id}")

    @work
    async def action_edit(self) -> None:
        await self._open_card("edit")

    @work
    async def action_complete(self) -> None:
        card_id = self._selected_card_id()
        if card_id is None:
            return
        summary = await self.push_screen_wait(CompleteScreen(card_id))
        if not summary:
            return
        service.complete_card(self._conn, card_id, summary=summary)
        self._reload()
        self._select_card(card_id)
        self.notify(f"Completed card #{card_id}")
