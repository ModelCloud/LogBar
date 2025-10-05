# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Column layout helpers for LogBar output."""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .terminal import terminal_size


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _visible_length(text: str) -> int:
    if not text:
        return 0
    cleaned = _strip_ansi(text)
    cleaned = cleaned.replace("\r", "").replace("\n", "")
    return len(cleaned)


def _pad_visible(text: str, target: int) -> str:
    current = _visible_length(text)
    if current >= target:
        return text
    return f"{text}{' ' * (target - current)}"


@dataclass
class ColumnSpec:
    label: str
    span: int = 1
    width: Optional[Tuple[str, float]] = None

    def __post_init__(self) -> None:
        if self.span < 1:
            self.span = 1


class ColumnsPrinter:
    """Helper that formats rows into aligned columns using `LogBar`."""

    class _LevelProxy:
        """Expose level-specific helpers such as `cols.info.header()`."""

        def __init__(self, printer: "ColumnsPrinter", level: Any) -> None:
            self._printer = printer
            self._level = level

        def __call__(self, *values: Any) -> str:
            return self._printer._log_values(self._level, values)

        def simulate(self, *values: Any) -> None:
            self._printer._simulate_values(self._level, values)

        def header(self) -> str:
            return self._printer._log_header(self._level)

        def headers(self) -> str:
            return self.header()

    def __init__(
        self,
        logger: Any,
        headers: Optional[Sequence] = None,
        *,
        padding: int = 2,
        width_hint: Optional[Union[str, int, float]] = None,
        level_enum: Any,
        level_max_length: int,
        terminal_size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
    ) -> None:
        self._logger = logger
        self._padding = max(padding, 0)
        self._columns: List[ColumnSpec] = []
        self._slot_widths: List[int] = []
        self._slot_padding: List[int] = []
        self._spec_starts: List[int] = []
        self._last_was_border = False
        self._target_width_hint: Optional[Tuple[str, float]] = self._parse_width_hint(width_hint)
        self._current_total_width: Optional[int] = None
        self._level_enum = level_enum
        self._level_max_length = level_max_length
        self._terminal_size = terminal_size_provider or terminal_size
        self._level_proxies: Dict[Any, ColumnsPrinter._LevelProxy] = {}

        if headers:
            self._set_columns(headers)

    @property
    def widths(self) -> List[int]:
        return list(self._slot_widths)

    @property
    def padding(self) -> int:
        return self._padding

    @property
    def column_specs(self) -> List[ColumnSpec]:
        return [ColumnSpec(spec.label, spec.span, spec.width) for spec in self._columns]

    def width(self, width: Optional[Union[str, int, float]] = None):
        if width is not None:
            raise TypeError(
                "ColumnsPrinter.width no longer accepts arguments; use ColumnsPrinter.update instead."
            )
        if self._current_total_width is not None:
            return self._current_total_width

        separator_count = 0
        slot_count = self._slot_count()
        if slot_count:
            separator_count = slot_count + 1

        return self._get_target_width() + separator_count

    def update(self, updates: Dict[str, Dict[str, Any]]):
        if not updates:
            return self

        modified = False
        for label, attrs in updates.items():
            spec_index = next((idx for idx, spec in enumerate(self._columns) if spec.label == label), None)
            if spec_index is None:
                raise KeyError(f"Unknown column label: {label!r}")

            spec = self._columns[spec_index]
            new_label = spec.label
            new_span = spec.span
            new_width = spec.width

            if not isinstance(attrs, dict):
                raise TypeError(
                    "Update values must be dictionaries mapping attribute names to values."
                )

            if "label" in attrs:
                new_label = str(attrs["label"]) if attrs["label"] is not None else ""

            if "span" in attrs:
                new_span = max(1, int(attrs["span"]))

            if "width" in attrs:
                new_width = self._parse_width_hint(attrs["width"])

            self._columns[spec_index] = ColumnSpec(label=new_label, span=new_span, width=new_width)
            modified = True

        if modified:
            self._recompute_layout()
            self._apply_initial_widths()
            self._apply_header_widths()

        return self

    def _level_proxy(self, level: Any) -> "ColumnsPrinter._LevelProxy":
        if level not in self._level_proxies:
            self._level_proxies[level] = ColumnsPrinter._LevelProxy(self, level)
        return self._level_proxies[level]

    @property
    def debug(self) -> "ColumnsPrinter._LevelProxy":
        return self._level_proxy(self._level_enum.DEBUG)

    @property
    def info(self) -> "ColumnsPrinter._LevelProxy":
        return self._level_proxy(self._level_enum.INFO)

    @property
    def warn(self) -> "ColumnsPrinter._LevelProxy":
        return self._level_proxy(self._level_enum.WARN)

    @property
    def error(self) -> "ColumnsPrinter._LevelProxy":
        return self._level_proxy(self._level_enum.ERROR)

    @property
    def critical(self) -> "ColumnsPrinter._LevelProxy":
        return self._level_proxy(self._level_enum.CRITICAL)

    def _log_header(self, level: Any) -> str:
        if not self._columns:
            return ""

        self._apply_header_widths()
        self._emit_border(level)
        row = self._render_header()
        self._print_row(level, row)
        self._emit_border(level, force=True)
        return row

    def _log_values(self, level: Any, values: Iterable) -> str:
        values_list = self._prepare_values(values)
        self._update_slot_widths(values_list)
        self._emit_border(level)
        row = self._render_row(values_list)
        self._print_row(level, row)
        self._emit_border(level, force=True)
        return row

    def _simulate_values(self, level: Any, values: Iterable) -> None:
        values_list = self._prepare_values(values)
        self._update_slot_widths(values_list)

    def _set_columns(self, headers: Sequence) -> None:
        self._columns = [self._normalize_column(entry) for entry in headers]
        self._recompute_layout()
        self._apply_initial_widths()
        self._apply_header_widths()

    def _normalize_column(self, entry) -> ColumnSpec:
        if isinstance(entry, ColumnSpec):
            label = entry.label
            span = entry.span
            width_hint = entry.width
        elif isinstance(entry, dict):
            label = str(entry.get("label") or entry.get("name") or "")
            span = int(entry.get("span", 1)) if entry.get("span") is not None else 1
            width_hint = self._parse_width_hint(entry.get("width"))
        elif isinstance(entry, (str, bytes)):
            label = str(entry)
            span = 1
            width_hint = None
        elif entry is None:
            label = ""
            span = 1
            width_hint = None
        else:
            raise TypeError(
                "Column definitions must be strings or dictionaries. "
                f"Received unsupported entry: {entry!r}"
            )

        return ColumnSpec(label=label, span=max(1, int(span)), width=width_hint)

    def _recompute_layout(self) -> None:
        starts: List[int] = []
        idx = 0
        for spec in self._columns:
            starts.append(idx)
            idx += spec.span
        self._spec_starts = starts
        slot_count = idx

        if len(self._slot_widths) < slot_count:
            self._slot_widths.extend([0] * (slot_count - len(self._slot_widths)))
        elif len(self._slot_widths) > slot_count:
            self._slot_widths = self._slot_widths[:slot_count]

        if len(self._slot_padding) < slot_count:
            self._slot_padding.extend([self._padding] * (slot_count - len(self._slot_padding)))
        elif len(self._slot_padding) > slot_count:
            self._slot_padding = self._slot_padding[:slot_count]

    def _parse_width_hint(self, value: Optional[Union[str, int, float]]) -> Optional[Tuple[str, float]]:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            if value <= 0:
                return None
            return ("chars", float(value))

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            lowered = raw.lower()
            if lowered == "fit":
                return ("fit", 0.0)
            if raw.endswith('%'):
                try:
                    ratio = float(raw[:-1]) / 100.0
                except ValueError:
                    return None
                if ratio <= 0:
                    return None
                return ("percent", ratio)
            try:
                numeric = float(raw)
            except ValueError:
                return None
            if numeric <= 0:
                return None
            return ("chars", numeric)

        return None

    def _minimal_width(self) -> int:
        if not self._columns:
            return 0
        slot_count = sum(spec.span for spec in self._columns)
        if slot_count == 0:
            return 0

        base_labels = sum(max(_visible_length(spec.label), 1) for spec in self._columns)
        padding_total = slot_count * (self._padding * 2)
        separators = slot_count + 1
        inter_column_gaps = max(0, slot_count - len(self._columns))
        return base_labels + padding_total + separators + inter_column_gaps

    def _get_target_width(self) -> int:
        hint = self._target_width_hint
        term_cols, _ = self._terminal_size()
        if term_cols <= 0:
            term_cols = 80

        slot_count = self._slot_count()
        separator_count = slot_count + 1 if slot_count else 0

        available_total = max(0, term_cols - (self._level_max_length + 2))

        if hint:
            if hint[0] == "percent":
                target_total = int(available_total * hint[1])
            else:
                target_total = int(hint[1])
        else:
            target_total = available_total

        minimal_total = self._minimal_width()
        if target_total <= 0:
            target_total = minimal_total

        target_total = max(target_total, minimal_total)

        if separator_count:
            minimal_cells = max(0, minimal_total - separator_count)
            target_cells = max(0, target_total - separator_count)
        else:
            minimal_cells = minimal_total
            target_cells = target_total

        return max(target_cells, minimal_cells)

    def _apply_initial_widths(self) -> None:
        slot_count = self._slot_count()
        if slot_count == 0:
            return

        self._slot_widths = [1] * slot_count
        self._slot_padding = [self._padding] * slot_count

        total_width = self._get_target_width()
        column_count = len(self._columns)

        for col_idx, spec in enumerate(self._columns):
            if spec.width is None:
                continue
            if spec.width[0] == "fit":
                continue
            target = self._resolve_width_hint(spec.width, total_width)
            self._configure_column_width(col_idx, target)

        current_total = sum(self._column_total_width(idx) for idx in range(column_count))
        has_percent = any(spec.width and spec.width[0] == "percent" for spec in self._columns)
        if current_total > total_width:
            total_width = current_total

        if not self._target_width_hint and not has_percent:
            total_width = current_total

        remaining = max(0, total_width - current_total)
        expandable = [idx for idx, spec in enumerate(self._columns) if spec.width is None]
        if not expandable:
            expandable = [
                idx
                for idx, spec in enumerate(self._columns)
                if spec.width is None or (spec.width and spec.width[0] != "fit")
            ]

        if remaining > 0 and expandable:
            while remaining > 0:
                progressed = False
                for col_idx in expandable:
                    if remaining <= 0:
                        break
                    spec = self._columns[col_idx]
                    if spec.width and spec.width[0] == "fit":
                        continue
                    self._grow_column(col_idx, 1)
                    remaining -= 1
                    progressed = True
                if not progressed:
                    break

        slot_count = self._slot_count()
        separator_count = slot_count + 1 if slot_count else 0
        current_total = sum(self._column_total_width(idx) for idx in range(column_count))
        self._current_total_width = current_total + separator_count

    def _resolve_width_hint(self, hint: Optional[Tuple[str, float]], total_width: int) -> Optional[int]:
        if not hint:
            return None
        if hint[0] == "percent":
            return max(0, int(total_width * hint[1]))
        return max(0, int(hint[1]))

    def _configure_column_width(self, col_idx: int, target: Optional[int]) -> None:
        start = self._spec_starts[col_idx]
        span = self._columns[col_idx].span
        if span <= 0:
            return

        slot_indices = [start + offset for offset in range(span) if start + offset < len(self._slot_widths)]
        if not slot_indices:
            return

        for idx in slot_indices:
            self._slot_padding[idx] = 0
            self._slot_widths[idx] = 1

        min_width = self._column_total_width(col_idx)
        if target is None or target < min_width:
            target = min_width

        extra = target - min_width
        while extra > 0:
            for idx in slot_indices:
                self._slot_widths[idx] += 1
                extra -= 1
                if extra <= 0:
                    break

    def _grow_column(self, col_idx: int, amount: int) -> None:
        if amount <= 0:
            return
        start = self._spec_starts[col_idx]
        span = self._columns[col_idx].span
        slot_indices = [start + offset for offset in range(span) if start + offset < len(self._slot_widths)]
        if not slot_indices:
            return
        while amount > 0:
            for idx in slot_indices:
                self._slot_widths[idx] += 1
                amount -= 1
                if amount <= 0:
                    break

    def _column_total_width(self, col_idx: int) -> int:
        start = self._spec_starts[col_idx]
        span = self._columns[col_idx].span
        total = 0
        for offset in range(span):
            slot_idx = start + offset
            if slot_idx >= len(self._slot_widths):
                break
            total += self._slot_widths[slot_idx] + (self._slot_padding[slot_idx] * 2)
        total += max(0, span - 1)
        return total

    def _slot_count(self) -> int:
        return len(self._slot_widths)

    def _ensure_slots(self, count: int) -> None:
        if count <= self._slot_count():
            return

        if not self._columns:
            self._columns = [ColumnSpec(label="", span=1) for _ in range(count)]
        else:
            extra = count - self._slot_count()
            last = self._columns[-1]
            self._columns[-1] = ColumnSpec(label=last.label, span=last.span + extra)

        self._recompute_layout()
        self._apply_initial_widths()
        self._apply_header_widths()

    def _apply_header_widths(self) -> None:
        if not self._columns:
            return

        for spec, start in zip(self._columns, self._spec_starts):
            span = spec.span
            if span <= 0:
                continue
            if start >= len(self._slot_widths):
                continue

            total_slot_width = 0
            for offset in range(span):
                idx = start + offset
                if idx >= len(self._slot_widths):
                    break
                total_slot_width += self._slot_widths[idx] + (self._slot_padding[idx] * 2)

            total_slot_width += max(0, span - 1)
            label_len = _visible_length(spec.label)

            left_pad = self._slot_padding[start]
            right_index = start + span - 1
            right_pad = self._slot_padding[right_index] if right_index < len(self._slot_padding) else self._padding

            inner_width = max(0, total_slot_width - left_pad - right_pad)

            if inner_width < label_len:
                deficit = label_len - inner_width
                self._slot_widths[start] += deficit

    def _prepare_values(self, values: Iterable) -> List[str]:
        values_list = [str(value) for value in values]
        self._ensure_slots(len(values_list))
        slot_count = self._slot_count()
        if len(values_list) < slot_count:
            values_list.extend([""] * (slot_count - len(values_list)))
        else:
            values_list = values_list[:slot_count]
        return values_list

    def _update_slot_widths(self, values: Iterable[str]) -> None:
        for idx, value in enumerate(values):
            if idx >= len(self._slot_widths):
                break
            current = _visible_length(value)
            if current > self._slot_widths[idx]:
                self._slot_widths[idx] = current

    def _render_header(self) -> str:
        cells: List[str] = []

        for idx, spec in enumerate(self._columns):
            span = max(1, spec.span)
            start = self._spec_starts[idx]
            total_width = self._column_total_width(idx)

            left_pad_val = self._slot_padding[start] if start < len(self._slot_padding) else self._padding
            right_index = start + span - 1
            right_pad_val = self._slot_padding[right_index] if right_index < len(self._slot_padding) else self._padding

            inner_width = max(0, total_width - left_pad_val - right_pad_val)
            pad_left = " " * left_pad_val
            pad_right = " " * right_pad_val
            content = _pad_visible(spec.label, inner_width)
            cells.append(f"{pad_left}{content}{pad_right}")

        return "|" + "|".join(cells) + "|"

    def _render_row(self, values: Iterable[str]) -> str:
        values_list = [str(value) for value in values]
        slot_count = self._slot_count()

        cells = []
        for idx in range(slot_count):
            text = values_list[idx] if idx < len(values_list) else ""
            if idx < len(self._slot_widths):
                width = self._slot_widths[idx]
            else:
                width = _visible_length(text)
            pad_width = self._slot_padding[idx] if idx < len(self._slot_padding) else self._padding
            pad = " " * pad_width
            padded_text = _pad_visible(text, width)
            cell = f"{pad}{padded_text}{pad}"
            cells.append(cell)

        return "|" + "|".join(cells) + "|"

    def _print_row(self, level: Any, row: str) -> None:
        self._last_was_border = False
        self._logger._process(level, row)

    def _emit_border(self, level: Any, force: bool = False) -> None:
        if not self._slot_widths:
            return

        if not force and self._last_was_border:
            return

        segments = []
        for idx, width in enumerate(self._slot_widths):
            base = max(1, width)
            padding = self._padding
            if idx < len(self._slot_padding):
                padding = max(0, self._slot_padding[idx])
            segments.append("-" * (base + (padding * 2)))

        border = "+" + "+".join(segments) + "+"
        self._logger._process(level, border)
        self._last_was_border = True
