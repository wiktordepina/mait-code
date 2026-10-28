"""A netext graph view that wears the active theme.

Shared by the TUIs that draw node-link diagrams &mdash; the knowledge-graph
explorer (``mait-code graph``) and the board's per-epic dependency diagram &mdash;
so neither pulls in the other's data layer to get it.
"""

from __future__ import annotations

from netext.textual_widget.widget import GraphView
from rich.style import Style
from textual.events import Resize
from textual.message import Message
from textual.strip import Strip

__all__ = ["ThemedGraphView"]


class ThemedGraphView(GraphView):
    """A GraphView whose canvas wears the theme background.

    netext emits its strips (and blank filler rows) with no background
    colour, and rendered lines bypass the CSS compositor - unstyled cells
    fall through to the *terminal's* default background instead of the
    theme's, leaving mismatched rectangles around the rendered graph.
    Laying the widget's resolved background under every line closes the gap.

    netext also builds nothing from a ``set_graph()`` made while the widget is
    hidden or not yet laid out, so it posts :class:`Sized` once it has a real
    size: the cue for a screen holding a graph to apply it. Waiting for that
    rather than retrying after each refresh matters: a callback that re-arms
    itself keeps the screen's queue busy, and the layout pass it waits for
    never runs.
    """

    class Sized(Message):
        """The view has just been laid out at a non-zero size."""

    def on_resize(self, message: Resize) -> None:
        # Textual runs GraphView's own resize handler too, after this one.
        if message.size.width and message.size.height:
            self.post_message(self.Sized())

    def render_line(self, y: int) -> Strip:
        base = Style(bgcolor=self.rich_style.bgcolor)
        return super().render_line(y).apply_style(base)
