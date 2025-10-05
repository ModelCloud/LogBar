# Copyright 2024-2025 ModelCloud.ai
# Copyright 2024-2025 qubitium@modelcloud.ai
# Contact: qubitium@modelcloud.ai, x.com/qubitium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Iterable, List, Sequence, Tuple, Union

from .terminal import terminal_size

# global static/shared logger instance
logger = None
last_pb_instance = None # one for logger, 2 for progressbar
last_rendered_length = 0

@dataclass
class ColumnSpec:
    label: str
    span: int = 1
    width: Optional[Tuple[str, float]] = None

    def __post_init__(self):
        if self.span < 1:
            self.span = 1

def update_last_pb_instance(src) -> None:
    global last_pb_instance
    last_pb_instance = src

# ANSI color codes
COLORS = {
    "DEBUG": "\033[36m",  # Cyan
    "INFO": "\033[32m",  # Green
    "WARN": "\033[33m",  # Yellow
    "ERROR": "\033[31m",  # Red
    "CRIT": "\033[31m",  # Red
    "RESET": "\033[0m",  # Reset to default
}

class LEVEL(str, Enum):
    DEBUG = "DEBUG"
    WARN = "WARN"
    INFO = "INFO"
    ERROR = "ERROR"
    CRITICAL = "CRIT"

LEVEL_MAX_LENGTH = 5 # ERROR/DEBUG is longest at 5 chars

class LogBar(logging.Logger):
    history = set()
    history_limit = 1000

    @classmethod
    # return a shared global/singleton logger
    def shared(cls, override_logger: Optional[bool] = False):
        global logger
        if logger is not None:
            return logger

        # save logger class
        if not override_logger:
            original_logger_cls = logging.getLoggerClass()

        logging.setLoggerClass(LogBar)

        logger = logging.getLogger("logbar")

        # restore logger cls
        if not override_logger:
            logging.setLoggerClass(original_logger_cls)

        logger.propagate = False
        logger.setLevel(logging.INFO)

        # handler = logging.StreamHandler(sys.stdout)
        # handler.setFormatter(formatter)
        # handler.flush = sys.stdout.flush
        # logger.addHandler(handler)

        # clear space from previous logs
        print("", end='\n', flush=True)

        return logger


    def pb(self, iterable: Iterable):
        from logbar.progress import ProgressBar

        return ProgressBar(iterable)

    def history_add(self, msg) -> bool:
        h = hash(msg) # TODO only msg is checked not level + msg
        if h in self.history:
            return False # add failed since it already exists

        if len(self.history) > self.history_limit:
            self.history.clear()

        self.history.add(h)

        return True

    class critical_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.CRITICAL, msg, *args, **kwargs)

    class warn_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.WARN, msg, *args, **kwargs)

    class debug_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.DEBUG, msg, *args, **kwargs)

    class info_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.INFO, msg, *args, **kwargs)

    class error_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.ERROR, msg, *args, **kwargs)

    def __init__(self, name):
        super().__init__(name)
        self._warning = self.warning
        self._debug = self.debug
        self._info = self.info
        self._error = self.error
        self._critical = self.critical

        self.warn = self.warn_cls(logger=self)
        self.debug = self.debug_cls(logger=self)
        self.info = self.info_cls(logger=self)
        self.error = self.error_cls(logger=self)
        self.critical = self.critical_cls(logger=self)

    def columns(self, *headers, cols: Optional[Sequence] = None, width: Optional[Union[str, int, float]] = None, padding: int = 2):
        """Return a column-aware helper that keeps column widths aligned."""

        header_defs: Optional[Sequence] = None

        if cols is not None:
            if isinstance(cols, (str, bytes)):
                header_defs = [cols]
            elif isinstance(cols, Iterable):
                header_defs = list(cols)
            else:
                header_defs = [cols]
        elif headers:
            if len(headers) == 1 and isinstance(headers[0], Iterable) and not isinstance(headers[0], (str, bytes)):
                header_defs = list(headers[0])
            else:
                header_defs = list(headers)

        return ColumnsPrinter(logger=self, headers=header_defs, padding=padding, width_hint=width)

    def _format_message(self, msg, args):
        """Format a log message while gracefully handling extra positional args."""
        if not args:
            return str(msg)

        remaining = list(args)
        parts = []

        def consume_format(fmt, available):
            if not isinstance(fmt, str):
                return str(fmt), 0

            if not available:
                return str(fmt), 0

            if len(available) == 1 and isinstance(available[0], dict):
                try:
                    return fmt % available[0], 1
                except (TypeError, ValueError, KeyError):
                    return str(fmt), 0

            for end in range(len(available), 0, -1):
                subset = tuple(available[:end])
                try:
                    return fmt % subset, end
                except (TypeError, ValueError, KeyError):
                    continue

            return str(fmt), 0

        current = msg
        while True:
            formatted, consumed = consume_format(current, remaining)
            parts.append(formatted)
            if consumed:
                remaining = remaining[consumed:]

            if not remaining:
                break

            next_candidate = remaining[0]
            if isinstance(next_candidate, str) and '%' in next_candidate:
                current = remaining.pop(0)
                continue

            break

        if remaining:
            parts.extend(str(arg) for arg in remaining)

        return " ".join(part for part in parts if part)

    def _process(self, level: LEVEL, msg, *args, **kwargs):
        from logbar.progress import ProgressBar

        global last_rendered_length
        columns, _ = terminal_size()
        str_msg = self._format_message(msg, args)

        line_length = len(level.value) + (LEVEL_MAX_LENGTH - len(level.value)) + 1 + len(str_msg)

        if columns > 0:
            padding_needed = max(0, columns - LEVEL_MAX_LENGTH - 2 - len(str_msg))
            str_msg += " " * padding_needed  # -2 for cursor + space between LEVEL and msg
            printable_length = columns
            last_rendered_length = printable_length
        else:
            printable_length = line_length
            if last_rendered_length > printable_length:
                str_msg += " " * (last_rendered_length - printable_length)

        global last_pb_instance
        if isinstance(last_pb_instance, ProgressBar) and not last_pb_instance.closed:
            print('\r',end='',flush=True)

        # Get the color for the log level

        reset = COLORS["RESET"]
        color = COLORS.get(level.value, reset)

        level_padding = " " * (LEVEL_MAX_LENGTH - len(level.value)) # 5 is max enum string length
        print(f"\r{color}{level.value}{reset}{level_padding} {str_msg}", end='\n', flush=True)

        if columns <= 0:
            last_rendered_length = printable_length

        if isinstance(last_pb_instance, ProgressBar):
            if not last_pb_instance.closed:
                # only do this for our instance
                if self == logger:
                    #print('\r', end='', flush=True)
                    last_pb_instance.draw()
            else:
                last_pb_instance = None


class ColumnsPrinter:
    """Helper that formats rows into aligned columns using `LogBar`."""

    def __init__(self, logger: LogBar, headers: Optional[Sequence] = None, *, padding: int = 2, width_hint: Optional[Union[str, int, float]] = None):
        self._logger = logger
        self._padding = max(padding, 0)
        self._columns: List[ColumnSpec] = []
        self._slot_widths: List[int] = []
        self._slot_padding: List[int] = []
        self._spec_starts: List[int] = []
        self._last_was_border = False
        self._target_width_hint: Optional[Tuple[str, float]] = self._parse_width_hint(width_hint)
        self._current_total_width: Optional[int] = None

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
        if width is None:
            if self._current_total_width is not None:
                return self._current_total_width
            return self._get_target_width()

        self._target_width_hint = self._parse_width_hint(width)
        self._apply_initial_widths()
        self._apply_header_widths()
        return self

    def render(self, level: Optional[LEVEL] = None):
        level = level or LEVEL.INFO
        if not self._columns:
            return ""

        self._apply_header_widths()
        self._emit_border(level)
        row = self._render_header()
        self._print_row(level, row)
        self._emit_border(level, force=True)
        return row

    def info(self, *values):
        return self._log_values(LEVEL.INFO, values)

    def debug(self, *values):
        return self._log_values(LEVEL.DEBUG, values)

    def warn(self, *values):
        return self._log_values(LEVEL.WARN, values)

    def error(self, *values):
        return self._log_values(LEVEL.ERROR, values)

    def critical(self, *values):
        return self._log_values(LEVEL.CRITICAL, values)

    def _log_values(self, level: LEVEL, values: Iterable) -> str:
        values_list = self._prepare_values(values)
        self._update_slot_widths(values_list)
        self._emit_border(level)
        row = self._render_row(values_list)
        self._print_row(level, row)
        self._emit_border(level, force=True)
        return row

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

        base_labels = sum(max(len(spec.label), 1) for spec in self._columns)
        padding_total = slot_count * (self._padding * 2)
        separators = slot_count + 1
        inter_column_gaps = max(0, slot_count - len(self._columns))
        return base_labels + padding_total + separators + inter_column_gaps

    def _get_target_width(self) -> int:
        hint = self._target_width_hint
        term_cols, _ = terminal_size()
        if term_cols <= 0:
            term_cols = 80

        available = max(0, term_cols - (LEVEL_MAX_LENGTH + 2))

        if hint:
            if hint[0] == "percent":
                target = int(available * hint[1])
            else:
                target = int(hint[1])
        else:
            target = available

        minimal = self._minimal_width()
        if target <= 0:
            target = minimal

        return max(target, minimal)

    def _apply_initial_widths(self) -> None:
        slot_count = self._slot_count()
        if slot_count == 0:
            return

        # reset base widths and padding
        self._slot_widths = [1] * slot_count
        self._slot_padding = [self._padding] * slot_count

        total_width = self._get_target_width()
        column_count = len(self._columns)

        # first satisfy explicit width hints
        for col_idx, spec in enumerate(self._columns):
            if spec.width is None:
                continue
            target = self._resolve_width_hint(spec.width, total_width)
            self._configure_column_width(col_idx, target)

        # compute current total and adjust to target
        current_total = sum(self._column_total_width(idx) for idx in range(column_count))
        if current_total > total_width:
            total_width = current_total

        remaining = max(0, total_width - current_total)
        expandable = [idx for idx, spec in enumerate(self._columns) if spec.width is None]
        if not expandable:
            expandable = list(range(column_count))

        while remaining > 0 and expandable:
            for col_idx in expandable:
                if remaining <= 0:
                    break
                self._grow_column(col_idx, 1)
                remaining -= 1

        self._current_total_width = sum(self._column_total_width(idx) for idx in range(column_count))

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

        # reduce padding to allow smaller widths when needed
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
            label_len = len(spec.label)

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
            current = len(value)
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
            content = spec.label.ljust(inner_width)
            cells.append(f"{pad_left}{content}{pad_right}")

        return "|" + "|".join(cells) + "|"

    def _render_row(self, values: Iterable[str]) -> str:
        values_list = [str(value) for value in values]
        slot_count = self._slot_count()

        cells = []
        for idx in range(slot_count):
            text = values_list[idx] if idx < len(values_list) else ""
            width = self._slot_widths[idx] if idx < len(self._slot_widths) else len(text)
            pad_width = self._slot_padding[idx] if idx < len(self._slot_padding) else self._padding
            pad = " " * pad_width
            cell = f"{pad}{text.ljust(width)}{pad}"
            cells.append(cell)

        return "|" + "|".join(cells) + "|"

    def _print_row(self, level: LEVEL, row: str) -> None:
        self._last_was_border = False
        self._logger._process(level, row)

    def _emit_border(self, level: LEVEL, force: bool = False) -> None:
        if not self._slot_widths:
            return

        if not force and self._last_was_border:
            return

        pad = self._padding * 2
        segments = []
        for width in self._slot_widths:
            base = max(1, width)
            segments.append("-" * (base + pad))

        border = "+" + "+".join(segments) + "+"
        self._logger._process(level, border)
        self._last_was_border = True
