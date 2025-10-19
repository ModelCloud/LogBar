# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import builtins
import logging
import os
import sys
import threading
import time
from enum import Enum
from typing import Iterable, Optional, Sequence, Union, TYPE_CHECKING

from .terminal import terminal_size
from .columns import ColumnSpec, ColumnsPrinter
from .buffer import get_buffered_stdout

# global static/shared logger instance
logger = None
last_rendered_length = 0

_STATE_LOCK = threading.RLock()
_RENDER_LOCK = threading.RLock()

def _stdout_stream():
    return get_buffered_stdout(sys.stdout)


def _write(data: str) -> int:
    stream = _stdout_stream()
    return stream.write(data)


def _flush_stream() -> None:
    stream = _stdout_stream()
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def _print(*args, **kwargs) -> None:
    if "file" not in kwargs:
        kwargs["file"] = _stdout_stream()
    kwargs.setdefault("flush", True)
    builtins.print(*args, **kwargs)

_notebook_display_handle = None
_notebook_plain_last_line: Optional[str] = None


def _running_in_notebook_environment() -> bool:
    """Best-effort detection for Jupyter-style REMOTE frontends."""

    if os.environ.get("LOGBAR_DISABLE_NOTEBOOK_DETECTION", "").strip():
        return False

    if os.environ.get("LOGBAR_FORCE_NOTEBOOK_MODE", "").strip():
        return True

    if os.environ.get("JPY_PARENT_PID") or os.environ.get("IPYKERNEL_PARENT_PID"):
        return True

    try:  # defer import to avoid hard dependency on IPython
        from IPython import get_ipython
    except Exception:  # pragma: no cover - IPython may not be installed
        return False

    try:
        ip = get_ipython()  # type: ignore
    except Exception:  # pragma: no cover - defensive for exotic shells
        return False

    if not ip:
        return False

    shell = getattr(ip, "__class__", None)
    shell_name = getattr(shell, "__name__", "")
    return shell_name == "ZMQInteractiveShell"


def _stdout_supports_cursor_movement() -> bool:
    stdout = sys.stdout
    isatty = getattr(stdout, "isatty", None)

    if callable(isatty):
        try:
            if isatty():
                return True
        except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
            return False

    if os.environ.get("LOGBAR_FORCE_TERMINAL_CURSOR", "").strip():
        return True

    # When in a notebook frontend, cursor movement is not reliably supported.
    if _running_in_notebook_environment():
        return False

    # Default to disabling cursor sequences when stdout is not a TTY.
    return False


def _notebook_render_stack(lines: Sequence[str]) -> bool:
    """Render the stack using IPython display machinery when available."""

    global _notebook_display_handle

    if not _running_in_notebook_environment():
        return False

    try:
        from IPython.display import display
    except Exception:
        return False

    text = '\n'.join(lines) if lines else ''
    payload = {'text/plain': text}

    try:
        handle = _notebook_display_handle
        if handle is None:
            handle = display(payload, raw=True, display_id=True)
            if handle is None:
                return False
            _notebook_display_handle = handle
        else:
            handle.update(payload, raw=True)

        if not lines:
            try:
                handle.update({'text/plain': ''}, raw=True)
            except Exception:
                pass
            try:
                handle.close()
            except Exception:
                pass
            _notebook_display_handle = None
    except Exception:
        _notebook_display_handle = None
        return False

    return True


def _notebook_render_plain_stdout(lines: Sequence[str]) -> None:
    """Fallback notebook-friendly rendering using carriage returns only."""

    global _notebook_plain_last_line

    if not lines:
        if _notebook_plain_last_line is not None:
            _write('\r')
            _write(' ' * len(_notebook_plain_last_line))
            _write('\r')
            _flush_stream()
        _notebook_plain_last_line = None
        return

    joined = '\n'.join(lines)

    if len(lines) == 1:
        previous = _notebook_plain_last_line or ''
        pad = len(previous) - len(joined)
        _write('\r')
        _write(joined)
        if pad > 0:
            _write(' ' * pad)
        _flush_stream()
        _notebook_plain_last_line = joined
        return

    # We cannot reposition multiple lines reliably without cursor controls. Emit the block once.
    _write('\r')
    _write(joined)
    _flush_stream()
    _notebook_plain_last_line = lines[-1]

def render_lock() -> threading.RLock:
    """Provide access to the shared render lock used for stdout writes."""

    return _RENDER_LOCK

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from .progress import ProgressBar

_attached_progress_bars = []  # type: list["ProgressBar"]
_last_drawn_progress_count = 0
_cursor_positioned_above_stack = False
_cursor_hidden = False
_refresh_thread: Optional[threading.Thread] = None
_REFRESH_INTERVAL_SECONDS = 0.1
_last_active_draw = 0.0


def attach_progress_bar(pb: "ProgressBar") -> None:
    """Register a progress bar so it participates in stacked rendering."""

    with _STATE_LOCK:
        if pb not in _attached_progress_bars:
            _attached_progress_bars.append(pb)
        _record_progress_activity_locked()
    _ensure_background_refresh_thread()


def detach_progress_bar(pb: "ProgressBar") -> None:
    """Stop managing a progress bar."""

    with _STATE_LOCK:
        if pb in _attached_progress_bars:
            _attached_progress_bars.remove(pb)
        _record_progress_activity_locked()


def _set_cursor_visibility_locked(visible: bool) -> None:
    """Toggle the terminal cursor visibility, avoiding redundant writes."""

    global _cursor_hidden

    if not _stdout_supports_cursor_movement():
        _cursor_hidden = False
        return

    hidden = not visible
    if _cursor_hidden == hidden:
        return

    code = '\033[?25h' if visible else '\033[?25l'
    _print(code, end='')
    _cursor_hidden = hidden


def _clear_progress_stack_locked(*, show_cursor: bool = True, for_log_output: bool = False) -> None:
    global _last_drawn_progress_count, _cursor_positioned_above_stack

    count = _last_drawn_progress_count
    supports_cursor = _stdout_supports_cursor_movement()

    if not supports_cursor:
        if not _notebook_render_stack([]):
            _notebook_render_plain_stdout([])
        _last_drawn_progress_count = 0
        _cursor_positioned_above_stack = False
        if show_cursor:
            _set_cursor_visibility_locked(True)
        return

    if count == 0:
        _cursor_positioned_above_stack = False
        if show_cursor:
            _set_cursor_visibility_locked(True)
        return

    sequences: list[str] = []

    if _cursor_positioned_above_stack:
        sequences.append('\033[1B')
    else:
        sequences.append('\r')
        if count > 1:
            sequences.append(f'\033[{count - 1}A')

    sequences.append('\r')
    sequences.append('\033[J')

    if for_log_output and count > 0:
        sequences.append('\033[1A')
        sequences.append('\r')

    if sequences:
        buffer = ''.join(sequences)
        if for_log_output and count > 0:
            buffer += '\033[1S'
        _write(buffer)
        _flush_stream()

    _last_drawn_progress_count = 0
    _cursor_positioned_above_stack = False
    if show_cursor:
        _set_cursor_visibility_locked(True)


def clear_progress_stack(lock_held: bool = False) -> None:
    """Erase any rendered progress bars from the terminal."""

    if lock_held:
        _clear_progress_stack_locked()
    else:
        with _RENDER_LOCK:
            _clear_progress_stack_locked()


def _active_progress_bars() -> list["ProgressBar"]:
    with _STATE_LOCK:
        return list(_attached_progress_bars)


def _render_progress_stack_locked(precomputed: Optional[dict] = None, columns_hint: Optional[int] = None) -> None:
    global _last_drawn_progress_count, _cursor_positioned_above_stack

    if columns_hint is not None:
        columns = columns_hint
    else:
        columns, _ = terminal_size()

    bars = _active_progress_bars()
    to_remove = []
    lines = []

    for pb in bars:
        if getattr(pb, "closed", False):
            to_remove.append(pb)
            continue

        rendered = None
        if precomputed is not None:
            rendered = precomputed.get(pb)

        if rendered is None:
            try:
                rendered = pb._render_snapshot(columns)
            except Exception:  # pragma: no cover - avoid breaking logging on render issues
                rendered = pb._last_rendered_line or ""
        else:
            pb._last_rendered_line = rendered

        lines.append(rendered or "")

    if to_remove:
        with _STATE_LOCK:
            for pb in to_remove:
                if pb in _attached_progress_bars:
                    _attached_progress_bars.remove(pb)

    supports_cursor = _stdout_supports_cursor_movement()

    if not supports_cursor:
        handled = _notebook_render_stack(lines)
        if not handled:
            _notebook_render_plain_stdout(lines)
            _flush_stream()
        _last_drawn_progress_count = 0
        _cursor_positioned_above_stack = False
        _set_cursor_visibility_locked(True)
        _record_progress_activity_locked()
        return

    previous_count = _last_drawn_progress_count
    sequences: list[str] = []

    if previous_count:
        if _cursor_positioned_above_stack:
            sequences.append('\033[1B')
        else:
            sequences.append('\r')
            if previous_count > 1:
                sequences.append(f'\033[{previous_count - 1}A')
        sequences.append('\r')
        sequences.append('\033[J')
    else:
        sequences.append('\r')

    if not lines:
        if sequences:
            _write(''.join(sequences))
        _flush_stream()
        _last_drawn_progress_count = 0
        _cursor_positioned_above_stack = False
        _set_cursor_visibility_locked(True)
        _record_progress_activity_locked()
        return

    for idx, line in enumerate(lines):
        sequences.append('\r')
        sequences.append(line)
        if idx < len(lines) - 1:
            sequences.append('\n')

    sequences.append('\r')
    sequences.append(f'\033[{len(lines)}A')

    _write(''.join(sequences))
    _flush_stream()
    _last_drawn_progress_count = len(lines)
    _cursor_positioned_above_stack = True
    _set_cursor_visibility_locked(False)
    _record_progress_activity_locked()


def render_progress_stack(lock_held: bool = False, precomputed: Optional[dict] = None, columns_hint: Optional[int] = None) -> None:
    """Redraw all attached progress bars respecting their attach order."""

    if lock_held:
        _render_progress_stack_locked(precomputed=precomputed, columns_hint=columns_hint)
    else:
        with _RENDER_LOCK:
            _render_progress_stack_locked(precomputed=precomputed, columns_hint=columns_hint)


def _record_progress_activity_locked() -> None:
    global _last_active_draw
    _last_active_draw = time.monotonic()


def _record_progress_activity() -> None:
    with _STATE_LOCK:
        _record_progress_activity_locked()


def _should_refresh_in_background(now: float) -> bool:
    stdout = sys.stdout
    isatty = getattr(stdout, "isatty", None)
    if callable(isatty):
        try:
            return bool(isatty())
        except Exception:  # pragma: no cover - defensive: prefer dropping animation over crashing
            return False
    return False


def _progress_refresh_worker() -> None:
    while True:
        time.sleep(_REFRESH_INTERVAL_SECONDS)

        now = time.monotonic()
        with _STATE_LOCK:
            has_progress = bool(_attached_progress_bars)
            last_active = _last_active_draw

        if not has_progress:
            continue

        if now - last_active < _REFRESH_INTERVAL_SECONDS:
            continue

        if not _should_refresh_in_background(now):
            continue

        try:
            if not _RENDER_LOCK.acquire(blocking=False):
                continue
            try:
                _render_progress_stack_locked()
            finally:
                _RENDER_LOCK.release()
        except Exception:
            continue


def _ensure_background_refresh_thread() -> None:
    global _refresh_thread

    with _STATE_LOCK:
        if _refresh_thread is not None and _refresh_thread.is_alive():
            return

        thread = threading.Thread(
            target=_progress_refresh_worker,
            name="logbar-progress-refresh",
            daemon=True,
        )
        _refresh_thread = thread
        thread.start()

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

        created_logger = False
        shared_logger = None

        with _STATE_LOCK:
            if logger is not None:
                shared_logger = logger
            else:
                original_logger_cls = None

                if not override_logger:
                    original_logger_cls = logging.getLoggerClass()

                logging.setLoggerClass(LogBar)
                try:
                    logger = logging.getLogger("logbar")
                finally:
                    if not override_logger and original_logger_cls is not None:
                        logging.setLoggerClass(original_logger_cls)

                logger.propagate = False
                logger.setLevel(logging.INFO)
                created_logger = True
                shared_logger = logger

        if shared_logger is None:
            shared_logger = logging.getLogger("logbar")

        if created_logger:
            with _RENDER_LOCK:
                # clear space from previous logs
                _print("", end='\n', flush=True)

        _ensure_background_refresh_thread()

        return shared_logger


    def pb(self, iterable: Iterable):
        from logbar.progress import ProgressBar

        return ProgressBar(iterable, owner=self).attach(self)

    def spinner(self, title: str = "", *, interval: float = 0.5, tail_length: int = 4):
        from logbar.progress import RollingProgressBar

        bar = RollingProgressBar(owner=self, interval=interval, tail_length=tail_length)
        if title:
            bar.title(title)
        return bar.attach(self)

    def history_add(self, msg) -> bool:
        h = hash(msg) # TODO only msg is checked not level + msg

        with self._history_lock:
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

        self.history = set()
        self._history_lock = threading.Lock()

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

        return ColumnsPrinter(
            logger=self,
            headers=header_defs,
            padding=padding,
            width_hint=width,
            level_enum=LEVEL,
            level_max_length=LEVEL_MAX_LENGTH,
            terminal_size_provider=lambda: terminal_size(),
        )

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
        global last_rendered_length

        str_msg = self._format_message(msg, args)

        with _RENDER_LOCK:
            columns, _ = terminal_size()

            with _STATE_LOCK:
                previous_render_length = last_rendered_length

            line_length = len(level.value) + (LEVEL_MAX_LENGTH - len(level.value)) + 1 + len(str_msg)

            if columns > 0:
                padding_needed = max(0, columns - LEVEL_MAX_LENGTH - 2 - len(str_msg))
                rendered_message = f"{str_msg}{' ' * padding_needed}"
                printable_length = columns
            else:
                printable_length = line_length
                excess_padding = max(0, previous_render_length - printable_length)
                rendered_message = f"{str_msg}{' ' * excess_padding}" if excess_padding else str_msg

            _clear_progress_stack_locked(for_log_output=True)

            reset = COLORS["RESET"]
            color = COLORS.get(level.value, reset)

            level_padding = " " * (LEVEL_MAX_LENGTH - len(level.value)) # 5 is max enum string length
            _print(f"\r{color}{level.value}{reset}{level_padding} {rendered_message}", end='\n', flush=True)

            with _STATE_LOCK:
                last_rendered_length = printable_length

            _render_progress_stack_locked()
