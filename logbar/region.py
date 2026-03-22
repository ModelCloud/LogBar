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
        if vertical_anchor not in {"top", "bottom"}:
            raise ValueError("vertical_anchor must be either 'top' or 'bottom'.")
        self._vertical_anchor: VerticalAnchor = vertical_anchor

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

        if context.viewport.height <= 0:
            return []
        if self._vertical_anchor == "bottom":
            return self._lines[-context.viewport.height:]
        return self._lines[:context.viewport.height]

    def render(self, context: RenderContext) -> CellBuffer:
        """Render the stored lines into a viewport-sized local cell buffer."""

        buffer = CellBuffer(context.viewport.width, context.viewport.height)
        if buffer.height <= 0 or buffer.width <= 0 or not self._lines:
            return buffer

        visible_lines = self.render_lines(context)
        if self._vertical_anchor == "bottom":
            start_row = max(0, buffer.height - len(visible_lines))
        else:
            start_row = 0

        for row_offset, line in enumerate(visible_lines):
            buffer.draw_text(0, start_row + row_offset, line[:buffer.width])

        return buffer


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

        buffer = CellBuffer(context.viewport.width, context.viewport.height)
        if buffer.height <= 0 or buffer.width <= 0:
            return buffer

        for row_idx, line in enumerate(self.render_lines(context)[:buffer.height]):
            buffer.draw_text(0, row_idx, line[:buffer.width])
        return buffer


__all__ = ["LineRegion", "LogRegion", "Region", "RenderContext", "TextRegion", "VerticalAnchor"]
