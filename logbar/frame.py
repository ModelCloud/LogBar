# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Cell-based frame primitives for future composited render backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .layout import Viewport


@dataclass(frozen=True)
class Cell:
    """Represent one terminal cell with an optional style token."""

    char: str = " "
    style: str = ""

    def __post_init__(self) -> None:
        """Normalize the cell payload to one visible character slot."""

        char = " " if not self.char else str(self.char)[0]
        object.__setattr__(self, "char", char)
        object.__setattr__(self, "style", str(self.style or ""))


class CellBuffer:
    """In-memory rectangular cell surface that supports clipping and blitting."""

    def __init__(self, width: int, height: int, fill: Optional[Cell] = None) -> None:
        """Create a new blank cell surface."""

        self.width = max(0, int(width))
        self.height = max(0, int(height))
        base = fill if fill is not None else Cell()
        self._rows: List[List[Cell]] = [
            [base for _ in range(self.width)]
            for _ in range(self.height)
        ]

    def viewport(self) -> Viewport:
        """Return the local bounds of this cell surface."""

        return Viewport(0, 0, self.width, self.height)

    def get_cell(self, x: int, y: int) -> Cell:
        """Return the cell at one coordinate or a blank cell when out of bounds."""

        if not self._in_bounds(x, y):
            return Cell()
        return self._rows[y][x]

    def set_cell(self, x: int, y: int, cell: Cell) -> None:
        """Write one cell when the coordinate falls inside the surface."""

        if not self._in_bounds(x, y):
            return
        self._rows[y][x] = cell

    def draw_text(self, x: int, y: int, text: str, *, style: str = "") -> None:
        """Write plain text left-to-right while clipping to the buffer bounds."""

        if y < 0 or y >= self.height:
            return

        cursor_x = int(x)
        for char in str(text):
            if 0 <= cursor_x < self.width:
                self._rows[y][cursor_x] = Cell(char=char, style=style)
            cursor_x += 1
            if cursor_x >= self.width:
                break

    def fill_viewport(self, viewport: Viewport, *, cell: Optional[Cell] = None) -> None:
        """Fill the overlap of a rectangle and the buffer bounds."""

        fill_cell = cell if cell is not None else Cell()
        clipped = viewport.intersection(self.viewport())
        for row in range(clipped.y, clipped.bottom):
            for col in range(clipped.x, clipped.right):
                self._rows[row][col] = fill_cell

    def blit(
        self,
        source: "CellBuffer",
        *,
        dest_x: int = 0,
        dest_y: int = 0,
        source_viewport: Optional[Viewport] = None,
    ) -> None:
        """Copy cells from a source surface into this one with clipping."""

        src_view = source_viewport if source_viewport is not None else source.viewport()
        src_view = src_view.intersection(source.viewport())

        for src_y in range(src_view.y, src_view.bottom):
            for src_x in range(src_view.x, src_view.right):
                target_x = dest_x + (src_x - src_view.x)
                target_y = dest_y + (src_y - src_view.y)
                if not self._in_bounds(target_x, target_y):
                    continue
                self._rows[target_y][target_x] = source.get_cell(src_x, src_y)

    def to_plain_lines(self) -> List[str]:
        """Serialize the buffer into plain-text lines for testable snapshots."""

        return ["".join(cell.char for cell in row) for row in self._rows]

    def _in_bounds(self, x: int, y: int) -> bool:
        """Return whether one coordinate falls inside the cell surface."""

        return 0 <= int(x) < self.width and 0 <= int(y) < self.height


__all__ = ["Cell", "CellBuffer"]
