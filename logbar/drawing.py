# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Shared ANSI-aware drawing primitives for terminal rendering."""

from dataclasses import dataclass
import re
from typing import Callable, Optional, Sequence


ANSI_RESET = "\033[0m"
ANSI_BOLD_RESET = "\033[22m"
TITLE_BASE_COLOR = "\033[38;5;250m"
TITLE_HIGHLIGHT_COLOR = "\033[1m\033[38;5;15m"
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")

BLOCK_PARTIAL_CHARS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")
SUBCELL_RESOLUTION = len(BLOCK_PARTIAL_CHARS) - 1


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def visible_length(text: str) -> int:
    if not text:
        return 0
    cleaned = strip_ansi(text)
    cleaned = cleaned.replace("\r", "").replace("\n", "")
    return len(cleaned)


def iter_ansi_tokens(text: str):
    i = 0
    while i < len(text):
        if text[i] == "\x1b":
            match = ANSI_ESCAPE_RE.match(text, i)
            if match:
                yield True, match.group(0)
                i = match.end()
                continue
        yield False, text[i]
        i += 1


def truncate_ansi(text: str, limit: int) -> str:
    if limit <= 0:
        return ANSI_RESET

    result = []
    printable = 0
    i = 0

    while i < len(text) and printable < limit:
        if text[i] == "\x1b":
            match = ANSI_ESCAPE_RE.match(text, i)
            if match:
                result.append(match.group(0))
                i = match.end()
                continue

        result.append(text[i])
        printable += 1
        i += 1

    if printable >= limit:
        result.append(ANSI_RESET)

    return "".join(result)


@dataclass(frozen=True)
class BarRenderResult:
    plain: str
    rendered: str


@dataclass(frozen=True)
class CellBarRenderer:
    """Rasterize a horizontal progress bar using terminal cell sub-divisions."""

    fill_char: str = "█"
    empty_char: str = " "
    head_char: Optional[str] = None
    partial_chars: Sequence[str] = BLOCK_PARTIAL_CHARS
    units_per_cell: int = SUBCELL_RESOLUTION

    def render(
        self,
        filled: int,
        empty: int,
        *,
        select_color: Optional[Callable[[int, int], str]] = None,
        empty_color: str = "",
        head_color: Optional[str] = None,
    ) -> BarRenderResult:
        filled = max(0, int(filled))
        empty = max(0, int(empty))
        return self.render_units(
            total_cells=filled + empty,
            filled_units=filled * self.units_per_cell,
            select_color=select_color,
            empty_color=empty_color,
            head_color=head_color,
        )

    def render_units(
        self,
        total_cells: int,
        filled_units: int,
        *,
        select_color: Optional[Callable[[int, int], str]] = None,
        empty_color: str = "",
        head_color: Optional[str] = None,
    ) -> BarRenderResult:
        width = max(0, int(total_cells))
        resolution = max(1, int(self.units_per_cell))

        if width == 0:
            return BarRenderResult("", "")

        total_units = width * resolution
        filled_units = max(0, min(int(filled_units), total_units))
        full_cells, partial_units = divmod(filled_units, resolution)
        occupied_cells = min(width, full_cells + (1 if partial_units else 0))

        color_selector = select_color or (lambda idx, total: "")
        plain_chars: list[str] = []
        rendered_segments: list[str] = []
        current_color: Optional[str] = None

        for idx in range(width):
            char = self._cell_char(idx, full_cells, partial_units)
            plain_chars.append(char)

            color = ""
            if idx < occupied_cells:
                color = color_selector(idx, occupied_cells)
                if head_color and idx == occupied_cells - 1:
                    color = head_color
            elif empty_color:
                color = empty_color

            if color != current_color:
                if current_color:
                    rendered_segments.append(ANSI_RESET)
                if color:
                    rendered_segments.append(color)
                current_color = color

            rendered_segments.append(char)

        if current_color:
            rendered_segments.append(ANSI_RESET)

        plain = "".join(plain_chars)
        return BarRenderResult(plain=plain, rendered="".join(rendered_segments))

    def _cell_char(self, idx: int, full_cells: int, partial_units: int) -> str:
        if idx < full_cells:
            if self.head_char and partial_units == 0 and idx == full_cells - 1:
                return self.head_char
            return self.fill_char

        if partial_units and idx == full_cells:
            return self._partial_char(partial_units)

        return self.empty_char

    def _partial_char(self, partial_units: int) -> str:
        if not self.partial_chars:
            return self.fill_char

        steps = len(self.partial_chars) - 1
        if steps <= 0:
            return self.fill_char

        scaled = (partial_units * steps + self.units_per_cell - 1) // self.units_per_cell
        scaled = max(1, min(steps, scaled))
        return self.partial_chars[scaled]
