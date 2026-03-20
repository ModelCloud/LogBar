# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Shared ANSI-aware drawing primitives for terminal rendering."""

from dataclasses import dataclass
from functools import lru_cache
import re
import unicodedata
from typing import Callable, Optional, Sequence


ANSI_RESET = "\033[0m"
ANSI_BOLD_RESET = "\033[22m"
TITLE_BASE_COLOR = "\033[38;5;250m"
TITLE_HIGHLIGHT_COLOR = "\033[1m\033[38;5;15m"
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")
TAB_STOP = 8

BLOCK_PARTIAL_CHARS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█")
SUBCELL_RESOLUTION = len(BLOCK_PARTIAL_CHARS) - 1

_ZERO_WIDTH_JOINER = "\u200d"
_EMOJI_TEXT_VARIATION = "\ufe0e"
_EMOJI_PRESENTATION_VARIATION = "\ufe0f"
_KEYCAP_COMBINING = "\u20e3"


@lru_cache(maxsize=8192)
def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


@lru_cache(maxsize=4096)
def _is_variation_selector(char: str) -> bool:
    codepoint = ord(char)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


@lru_cache(maxsize=4096)
def _is_regional_indicator(char: str) -> bool:
    codepoint = ord(char)
    return 0x1F1E6 <= codepoint <= 0x1F1FF


@lru_cache(maxsize=4096)
def _is_emoji_modifier(char: str) -> bool:
    codepoint = ord(char)
    return 0x1F3FB <= codepoint <= 0x1F3FF


@lru_cache(maxsize=4096)
def _is_keycap_base(char: str) -> bool:
    return char.isdigit() or char in {"#", "*"}


@lru_cache(maxsize=4096)
def _is_combining_like(char: str) -> bool:
    if char == _ZERO_WIDTH_JOINER:
        return False

    if char in {_EMOJI_TEXT_VARIATION, _EMOJI_PRESENTATION_VARIATION, _KEYCAP_COMBINING}:
        return True

    if _is_variation_selector(char) or _is_emoji_modifier(char):
        return True

    category = unicodedata.category(char)
    if category in {"Mn", "Me"}:
        return True

    if category == "Cf":
        return True

    return unicodedata.combining(char) != 0


@lru_cache(maxsize=4096)
def _can_expand_to_emoji(char: str) -> bool:
    codepoint = ord(char)
    return (
        char in {"#", "*"}
        or "0" <= char <= "9"
        or 0x2600 <= codepoint <= 0x27BF
        or 0x1F000 <= codepoint <= 0x1FAFF
    )


@lru_cache(maxsize=4096)
def _base_cell_width(char: str) -> int:
    if not char:
        return 0

    if char in {"\r", "\n"}:
        return 0

    if char == "\t":
        return 1

    if _is_combining_like(char):
        return 0

    category = unicodedata.category(char)
    if category.startswith("C"):
        return 0

    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 2

    return 1


def _consume_plain_cluster(text: str, start: int) -> tuple[str, int]:
    length = len(text)
    cluster = [text[start]]
    i = start + 1

    if _is_regional_indicator(cluster[0]) and i < length and _is_regional_indicator(text[i]):
        cluster.append(text[i])
        i += 1

    while i < length and _is_combining_like(text[i]):
        cluster.append(text[i])
        i += 1

    if i < length and text[i] == _KEYCAP_COMBINING and _is_keycap_base(cluster[0]):
        cluster.append(text[i])
        i += 1

    while i < length and text[i] == _ZERO_WIDTH_JOINER:
        cluster.append(text[i])
        i += 1
        if i >= length:
            break

        cluster.append(text[i])
        i += 1

        while i < length and _is_combining_like(text[i]):
            cluster.append(text[i])
            i += 1

        if i < length and text[i] == _KEYCAP_COMBINING and _is_keycap_base(cluster[-1]):
            cluster.append(text[i])
            i += 1

    return "".join(cluster), i


@lru_cache(maxsize=8192)
def _cluster_cell_width(cluster: str) -> int:
    if not cluster:
        return 0

    if any(ch in {"\r", "\n"} for ch in cluster):
        return 0

    if _KEYCAP_COMBINING in cluster:
        return 2

    if any(_is_regional_indicator(ch) for ch in cluster):
        return 2

    if _ZERO_WIDTH_JOINER in cluster:
        return 2 if any(_base_cell_width(ch) > 0 for ch in cluster) else 0

    width = sum(_base_cell_width(ch) for ch in cluster)
    if width <= 0:
        return 0

    if _EMOJI_PRESENTATION_VARIATION in cluster and any(_can_expand_to_emoji(ch) for ch in cluster):
        return max(2, width)

    return width


def _iter_plain_clusters(text: str):
    i = 0
    while i < len(text):
        cluster, i = _consume_plain_cluster(text, i)
        yield cluster


def iter_display_atoms(text: str):
    column = 0
    i = 0
    while i < len(text):
        if text[i] == "\x1b":
            match = ANSI_ESCAPE_RE.match(text, i)
            if match:
                yield True, match.group(0), 0
                i = match.end()
                continue

        cluster, i = _consume_plain_cluster(text, i)
        if cluster == "\t":
            remainder = column % TAB_STOP
            width = TAB_STOP if remainder == 0 else TAB_STOP - remainder
        else:
            width = _cluster_cell_width(cluster)

        yield False, cluster, width

        if cluster in {"\r", "\n"}:
            column = 0
        else:
            column += width


@lru_cache(maxsize=8192)
def visible_length(text: str) -> int:
    if not text:
        return 0

    printable = 0
    for is_ansi, _token, width in iter_display_atoms(text):
        if not is_ansi:
            printable += width
    return printable


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


@lru_cache(maxsize=8192)
def truncate_ansi(text: str, limit: int) -> str:
    if limit <= 0:
        return ANSI_RESET

    result = []
    printable = 0

    for is_ansi, token, width in iter_display_atoms(text):
        if is_ansi:
            result.append(token)
            continue

        if printable + width > limit:
            break

        result.append(token)
        printable += width

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
