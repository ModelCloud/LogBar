# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Region rendering primitives for future composited LogBar backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from .frame import CellBuffer
from .layout import Viewport


VerticalAnchor = Literal["top", "bottom"]


@dataclass(frozen=True)
class RenderContext:
    """Describe the viewport and policy passed into one region render call."""

    viewport: Viewport
    root_viewport: Viewport
    style_enabled: bool = True


class Region:
    """Base class for renderable rectangular regions."""

    def render(self, context: RenderContext) -> CellBuffer:
        """Render the region into a local cell buffer sized to its viewport."""

        raise NotImplementedError


def _normalize_vertical_anchor(vertical_anchor: VerticalAnchor) -> VerticalAnchor:
    """Validate and normalize one line-region anchoring policy."""

    if vertical_anchor not in {"top", "bottom"}:
        raise ValueError("vertical_anchor must be either 'top' or 'bottom'.")
    return vertical_anchor


def clip_rendered_lines(
    lines: Sequence[str],
    *,
    height: int,
    vertical_anchor: VerticalAnchor = "top",
) -> list[str]:
    """Clip one rendered line list to the visible viewport height."""

    max_rows = max(0, int(height))
    if max_rows <= 0:
        return []

    rendered = [str(line) for line in lines]
    if len(rendered) <= max_rows:
        return rendered

    normalized_anchor = _normalize_vertical_anchor(vertical_anchor)
    if normalized_anchor == "bottom":
        return rendered[-max_rows:]
    return rendered[:max_rows]


def line_region_start_row(
    *,
    height: int,
    line_count: int,
    vertical_anchor: VerticalAnchor = "top",
) -> int:
    """Resolve the first visible row for one vertically anchored line list."""

    if height <= 0 or line_count <= 0:
        return 0

    normalized_anchor = _normalize_vertical_anchor(vertical_anchor)
    if normalized_anchor == "bottom":
        return max(0, int(height) - int(line_count))
    return 0


def render_line_buffer(
    lines: Sequence[str],
    context: RenderContext,
    *,
    vertical_anchor: VerticalAnchor = "top",
) -> CellBuffer:
    """Render one line list into a viewport-sized local cell buffer."""

    buffer = CellBuffer(context.viewport.width, context.viewport.height)
    if buffer.height <= 0 or buffer.width <= 0:
        return buffer

    visible_lines = clip_rendered_lines(
        lines,
        height=buffer.height,
        vertical_anchor=vertical_anchor,
    )
    start_row = line_region_start_row(
        height=buffer.height,
        line_count=len(visible_lines),
        vertical_anchor=vertical_anchor,
    )
    for row_offset, line in enumerate(visible_lines):
        buffer.draw_text(0, start_row + row_offset, str(line)[:buffer.width])
    return buffer


class LineRegion(Region):
    """Simple line-oriented region used for the transitional ANSI backend path."""

    def __init__(
        self,
        lines: Optional[Sequence[str]] = None,
        *,
        vertical_anchor: VerticalAnchor = "top",
    ) -> None:
        """Store plain lines that will be clipped into the target viewport."""

        self._lines = [str(line) for line in (lines or ())]
        self._vertical_anchor = _normalize_vertical_anchor(vertical_anchor)

    @property
    def lines(self) -> list[str]:
        """Return a defensive copy of the stored plain-text lines."""

        return list(self._lines)

    @property
    def vertical_anchor(self) -> VerticalAnchor:
        """Return the configured vertical anchoring policy."""

        return self._vertical_anchor

    def set_lines(self, lines: Sequence[str]) -> "LineRegion":
        """Replace the stored lines and return the region for chaining."""

        self._lines = [str(line) for line in lines]
        return self

    def render_lines(self, context: RenderContext) -> list[str]:
        """Return the visible subset of stored lines for one viewport."""

        return clip_rendered_lines(
            self._lines,
            height=context.viewport.height,
            vertical_anchor=self._vertical_anchor,
        )

    def render(self, context: RenderContext) -> CellBuffer:
        """Render the stored lines into a viewport-sized local cell buffer."""

        return render_line_buffer(
            self._lines,
            context,
            vertical_anchor=self._vertical_anchor,
        )


class TextRegion(LineRegion):
    """Compatibility alias for plain-text regions backed by line rendering."""


class LogRegion(Region):
    """Pane-like region with scrollable body lines and anchored footer lines."""

    vertical_anchor: VerticalAnchor = "top"

    def __init__(
        self,
        body_lines: Optional[Sequence[str]] = None,
        *,
        footer_lines: Optional[Sequence[str]] = None,
    ) -> None:
        """Store body and footer content independently for one region."""

        self._body_lines = [str(line) for line in (body_lines or ())]
        self._footer_lines = [str(line) for line in (footer_lines or ())]

    @property
    def body_lines(self) -> list[str]:
        """Return a defensive copy of the current body scrollback."""

        return list(self._body_lines)

    @property
    def footer_lines(self) -> list[str]:
        """Return a defensive copy of the current footer rows."""

        return list(self._footer_lines)

    def set_body_lines(self, lines: Sequence[str]) -> "LogRegion":
        """Replace the visible body scrollback source."""

        self._body_lines = [str(line) for line in lines]
        return self

    def append_body_line(self, line: str) -> "LogRegion":
        """Append one new body line to the region scrollback."""

        self._body_lines.append(str(line))
        return self

    def extend_body_lines(self, lines: Sequence[str]) -> "LogRegion":
        """Append multiple body lines in order."""

        self._body_lines.extend(str(line) for line in lines)
        return self

    def clear_body(self) -> "LogRegion":
        """Remove all body content from the region."""

        self._body_lines = []
        return self

    def set_footer_lines(self, lines: Sequence[str]) -> "LogRegion":
        """Replace the anchored footer rows."""

        self._footer_lines = [str(line) for line in lines]
        return self

    def append_footer_line(self, line: str) -> "LogRegion":
        """Append one footer row at the bottom of the region."""

        self._footer_lines.append(str(line))
        return self

    def extend_footer_lines(self, lines: Sequence[str]) -> "LogRegion":
        """Append multiple footer rows in order."""

        self._footer_lines.extend(str(line) for line in lines)
        return self

    def clear_footer(self) -> "LogRegion":
        """Remove all footer content from the region."""

        self._footer_lines = []
        return self

    def render_lines(self, context: RenderContext) -> list[str]:
        """Render body scrollback above anchored footer rows inside the viewport."""

        height = max(0, int(context.viewport.height))
        if height <= 0:
            return []

        footer_visible = self._footer_lines[-height:]
        footer_count = min(len(footer_visible), height)
        body_height = max(0, height - footer_count)
        body_visible = self._body_lines[-body_height:] if body_height > 0 else []

        rows = [""] * height
        body_start = max(0, body_height - len(body_visible))
        for idx, line in enumerate(body_visible):
            rows[body_start + idx] = line

        footer_start = height - footer_count
        for idx, line in enumerate(footer_visible):
            rows[footer_start + idx] = line

        return rows

    def render(self, context: RenderContext) -> CellBuffer:
        """Render the pane content into a viewport-sized local cell buffer."""

        return render_line_buffer(
            self.render_lines(context),
            context,
            vertical_anchor=self.vertical_anchor,
        )


__all__ = [
    "LineRegion",
    "LogRegion",
    "Region",
    "RenderContext",
    "TextRegion",
    "VerticalAnchor",
    "clip_rendered_lines",
    "line_region_start_row",
    "render_line_buffer",
]
