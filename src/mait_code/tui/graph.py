"""A netext graph view that wears the active theme.

Shared by the TUIs that draw node-link diagrams &mdash; the knowledge-graph
explorer (``mait-code graph``) and the board's per-epic dependency diagram &mdash;
so neither pulls in the other's data layer to get it.
"""

from __future__ import annotations

from netext.textual_widget.widget import GraphView
from rich.style import Style
from textual.strip import Strip

__all__ = ["ThemedGraphView"]


class ThemedGraphView(GraphView):
    """A GraphView whose canvas wears the theme background.

    netext emits its strips (and blank filler rows) with no background
    colour, and rendered lines bypass the CSS compositor — unstyled cells
    fall through to the *terminal's* default background instead of the
    theme's, leaving mismatched rectangles around the rendered graph.
    Laying the widget's resolved background under every line closes the gap.
    """

    def render_line(self, y: int) -> Strip:
        base = Style(bgcolor=self.rich_style.bgcolor)
        return super().render_line(y).apply_style(base)
