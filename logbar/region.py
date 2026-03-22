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


class TextRegion(Region):
    """Simple plain-text region used for early coordinator composition tests."""

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

    def set_lines(self, lines: Sequence[str]) -> "TextRegion":
        """Replace the stored lines and return the region for chaining."""

        self._lines = [str(line) for line in lines]
        return self

    def render(self, context: RenderContext) -> CellBuffer:
        """Render the stored lines into a viewport-sized local cell buffer."""

        buffer = CellBuffer(context.viewport.width, context.viewport.height)
        if buffer.height <= 0 or buffer.width <= 0 or not self._lines:
            return buffer

        visible_lines = self._lines[-buffer.height:] if self._vertical_anchor == "bottom" else self._lines[:buffer.height]
        if self._vertical_anchor == "bottom":
            start_row = max(0, buffer.height - len(visible_lines))
        else:
            start_row = 0

        for row_offset, line in enumerate(visible_lines):
            buffer.draw_text(0, start_row + row_offset, line[:buffer.width])

        return buffer


__all__ = ["Region", "RenderContext", "TextRegion", "VerticalAnchor"]
