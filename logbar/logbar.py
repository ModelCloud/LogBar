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

from .terminal import RenderBackendState, render_backend_state, terminal_size
from .columns import ColumnSpec, ColumnsPrinter
from .buffer import get_buffered_stdout
from .drawing import ansi_to_html, strip_ansi, visible_length

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


def _current_render_backend_state(columns_hint: Optional[int] = None) -> RenderBackendState:
    notebook = _running_in_notebook_environment()

    if columns_hint is not None:
        def _size_provider():
            _, lines = terminal_size()
            return (columns_hint, lines)
    else:
        _size_provider = terminal_size

    return render_backend_state(
        stream=sys.stdout,
        size_provider=_size_provider,
        notebook=notebook,
    )


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
    try:
        state = _current_render_backend_state()
    except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
        return False
    return state.supports_cursor


def _stdout_supports_ansi() -> bool:
    try:
        state = _current_render_backend_state()
    except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
        return False
    return state.supports_ansi


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
    plain_text = strip_ansi(text)
    payload = {
        'text/plain': plain_text,
        'text/html': (
            '<pre style="margin:0; white-space:pre; '
            'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">'
            f'{ansi_to_html(text)}'
            '</pre>'
        ),
    }

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
                handle.update(
                    {
                        'text/plain': '',
                        'text/html': (
                            '<pre style="margin:0; white-space:pre; '
                            'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"></pre>'
                        ),
                    },
                    raw=True,
                )
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


def _notebook_render_plain_stdout(lines: Sequence[str], *, strip_styles: bool = False) -> None:
    """Fallback notebook-friendly rendering using carriage returns only."""

    global _notebook_plain_last_line

    if strip_styles:
        lines = [strip_ansi(line) for line in lines]

    if not lines:
        if _notebook_plain_last_line is not None:
            _write('\r')
            _write(' ' * visible_length(_notebook_plain_last_line))
            _write('\r')
            _flush_stream()
        _notebook_plain_last_line = None
        return

    joined = '\n'.join(lines)

    if len(lines) == 1:
        previous = _notebook_plain_last_line or ''
        pad = visible_length(previous) - visible_length(joined)
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
_dirty_progress_bars = set()  # type: set["ProgressBar"]
_last_drawn_progress_count = 0
_last_rendered_terminal_size: Optional[tuple[int, int]] = None
_last_rendered_progress_lines: list[str] = []
_cursor_positioned_above_stack = False
_cursor_positioned_on_stack_top = False
_stack_redraw_invalidated = False
_deferred_log_records: list[tuple[int, str]] = []
_cursor_hidden = False
_refresh_thread: Optional[threading.Thread] = None
_REFRESH_INTERVAL_SECONDS = 0.1
_last_active_draw = 0.0


def _set_stack_cursor_anchor(line_count: int, terminal_rows: int) -> None:
    global _cursor_positioned_above_stack, _cursor_positioned_on_stack_top

    if line_count <= 0:
        _cursor_positioned_above_stack = False
        _cursor_positioned_on_stack_top = False
        return

    if terminal_rows > 0 and line_count >= terminal_rows:
        _cursor_positioned_above_stack = False
        _cursor_positioned_on_stack_top = True
        return

    _cursor_positioned_above_stack = True
    _cursor_positioned_on_stack_top = False


def _should_defer_log_output_locked(terminal_rows: int) -> bool:
    if _last_drawn_progress_count <= 0:
        return False

    if terminal_rows <= 0:
        return False

    return (
        _last_drawn_progress_count >= terminal_rows
        and not _cursor_positioned_above_stack
    )


def _flush_deferred_logs_locked() -> None:
    global _deferred_log_records

    if not _deferred_log_records or logger is None:
        return

    pending = list(_deferred_log_records)
    _deferred_log_records = []

    for normalized_level, str_msg in pending:
        level_label = LOGGING_TO_LEVEL_LABEL.get(
            normalized_level,
            str(logging.getLevelName(normalized_level)),
        )
        logger._emit_log_line_locked(
            normalized_level,
            level_label,
            str_msg,
            allow_defer=False,
        )


def attach_progress_bar(pb: "ProgressBar") -> None:
    """Register a progress bar so it participates in stacked rendering."""

    with _STATE_LOCK:
        if pb not in _attached_progress_bars:
            _attached_progress_bars.append(pb)
        _dirty_progress_bars.add(pb)
        _record_progress_activity_locked()
    _ensure_background_refresh_thread()


def detach_progress_bar(pb: "ProgressBar") -> None:
    """Stop managing a progress bar."""

    with _STATE_LOCK:
        if pb in _attached_progress_bars:
            _attached_progress_bars.remove(pb)
        _dirty_progress_bars.discard(pb)
        _record_progress_activity_locked()


def mark_progress_bar_dirty(pb: "ProgressBar") -> None:
    with _STATE_LOCK:
        if pb in _attached_progress_bars:
            _dirty_progress_bars.add(pb)
        _record_progress_activity_locked()


def _set_cursor_visibility_locked(visible: bool, backend_state: Optional[RenderBackendState] = None) -> None:
    """Toggle the terminal cursor visibility, avoiding redundant writes."""

    global _cursor_hidden

    state = backend_state
    if state is None:
        try:
            state = _current_render_backend_state()
        except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
            state = None

    if state is None or not state.supports_cursor:
        _cursor_hidden = False
        return

    hidden = not visible
    if _cursor_hidden == hidden:
        return

    code = '\033[?25h' if visible else '\033[?25l'
    _print(code, end='')
    _cursor_hidden = hidden


def _clear_progress_stack_locked(
    *,
    show_cursor: bool = True,
    for_log_output: bool = False,
    backend_state: Optional[RenderBackendState] = None,
) -> None:
    global _last_drawn_progress_count, _last_rendered_terminal_size, _last_rendered_progress_lines, _cursor_positioned_above_stack, _cursor_positioned_on_stack_top, _stack_redraw_invalidated

    count = _last_drawn_progress_count
    state = backend_state or _current_render_backend_state()
    supports_cursor = state.supports_cursor

    if not supports_cursor:
        if not _notebook_render_stack([]):
            _notebook_render_plain_stdout([], strip_styles=state.notebook)
        _last_drawn_progress_count = 0
        _last_rendered_terminal_size = None
        _last_rendered_progress_lines = []
        _cursor_positioned_above_stack = False
        _cursor_positioned_on_stack_top = False
        _stack_redraw_invalidated = False
        if show_cursor:
            _set_cursor_visibility_locked(True, backend_state=state)
        if not for_log_output:
            _flush_deferred_logs_locked()
        return

    if count == 0:
        _last_rendered_terminal_size = None
        _last_rendered_progress_lines = []
        _cursor_positioned_above_stack = False
        _cursor_positioned_on_stack_top = False
        _stack_redraw_invalidated = False
        if show_cursor:
            _set_cursor_visibility_locked(True, backend_state=state)
        if not for_log_output:
            _flush_deferred_logs_locked()
        return

    sequences: list[str] = []

    if _cursor_positioned_above_stack:
        sequences.append('\033[1B')
    elif _cursor_positioned_on_stack_top:
        sequences.append('\r')
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
    _last_rendered_terminal_size = None
    _last_rendered_progress_lines = []
    _cursor_positioned_above_stack = False
    _cursor_positioned_on_stack_top = False
    _stack_redraw_invalidated = False
    if show_cursor:
        _set_cursor_visibility_locked(True, backend_state=state)
    if not for_log_output:
        _flush_deferred_logs_locked()


def _prepare_progress_stack_for_log_locked() -> bool:
    """Write a log line above the active stack and force a full redraw afterward."""

    global _stack_redraw_invalidated

    count = _last_drawn_progress_count
    if count == 0:
        return False

    if not _stdout_supports_cursor_movement():
        return False

    if not _cursor_positioned_above_stack:
        return False

    # The newline for the log line will briefly land on the first stack row.
    # Force the next stack paint to be a full redraw so any overwritten rows
    # are restored even when the frame contents are otherwise unchanged.
    _stack_redraw_invalidated = True
    return True


def clear_progress_stack(lock_held: bool = False, backend_state: Optional[RenderBackendState] = None) -> None:
    """Erase any rendered progress bars from the terminal."""

    if lock_held:
        _clear_progress_stack_locked(backend_state=backend_state)
    else:
        with _RENDER_LOCK:
            _clear_progress_stack_locked(backend_state=backend_state)


def _active_progress_bars() -> list["ProgressBar"]:
    with _STATE_LOCK:
        return list(_attached_progress_bars)


def _call_resolve_rendered_line(
    resolve_rendered,
    columns: int,
    *,
    force: bool,
    allow_repeat: bool,
    backend_state: RenderBackendState,
) -> Optional[str]:
    try:
        return resolve_rendered(
            columns,
            force=force,
            allow_repeat=allow_repeat,
            backend_state=backend_state,
            style_enabled=backend_state.supports_styling,
        )
    except TypeError as exc:
        message = str(exc)
        if "backend_state" not in message and "style_enabled" not in message:
            raise
        return resolve_rendered(
            columns,
            force=force,
            allow_repeat=allow_repeat,
        )


def _render_progress_stack_locked(
    precomputed: Optional[dict] = None,
    columns_hint: Optional[int] = None,
    backend_state: Optional[RenderBackendState] = None,
) -> None:
    global _last_drawn_progress_count, _last_rendered_terminal_size, _last_rendered_progress_lines, _cursor_positioned_above_stack, _cursor_positioned_on_stack_top, _stack_redraw_invalidated

    state = backend_state or _current_render_backend_state(columns_hint)
    columns = state.columns
    rows = state.lines

    bars = _active_progress_bars()
    with _STATE_LOCK:
        dirty_bars = set(_dirty_progress_bars)
    to_remove = []
    lines = []
    size_changed = _last_rendered_terminal_size != (max(0, int(columns)), max(0, int(rows)))

    for pb in bars:
        if getattr(pb, "closed", False):
            to_remove.append(pb)
            continue

        rendered = None
        if precomputed is not None:
            rendered = precomputed.get(pb)

        if rendered is None:
            try:
                resolve_rendered = getattr(pb, "_resolve_rendered_line", None)
                dirty_tracked = bool(getattr(pb, "_logbar_dirty_tracked", False))
                should_refresh = (
                    size_changed
                    or pb in dirty_bars
                    or not pb._last_rendered_line
                    or not dirty_tracked
                )
                if not should_refresh and pb._last_rendered_line:
                    rendered = pb._last_rendered_line
                elif callable(resolve_rendered):
                    rendered = _call_resolve_rendered_line(
                        resolve_rendered,
                        columns,
                        force=size_changed,
                        allow_repeat=(size_changed or pb in dirty_bars),
                        backend_state=state,
                    )
                    if rendered is None:
                        rendered = pb._last_rendered_line or ""
                else:
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
                _dirty_progress_bars.discard(pb)

    supports_cursor = state.supports_cursor

    if not supports_cursor:
        handled = _notebook_render_stack(lines)
        if not handled:
            _notebook_render_plain_stdout(lines, strip_styles=state.notebook)
            _flush_stream()
        with _STATE_LOCK:
            _dirty_progress_bars.difference_update(bars)
        _last_drawn_progress_count = 0
        _last_rendered_terminal_size = None
        _last_rendered_progress_lines = []
        _cursor_positioned_above_stack = False
        _cursor_positioned_on_stack_top = False
        _stack_redraw_invalidated = False
        _set_cursor_visibility_locked(True, backend_state=state)
        _record_progress_activity_locked()
        return

    terminal_columns = max(0, int(columns))
    terminal_rows = max(0, int(rows))
    if terminal_rows > 0 and len(lines) > terminal_rows:
        lines = lines[-terminal_rows:]

    previous_count = _last_drawn_progress_count
    previous_lines = list(_last_rendered_progress_lines)
    sequences: list[str] = []

    can_diff_redraw = (
        previous_count > 0
        and (_cursor_positioned_above_stack or _cursor_positioned_on_stack_top)
        and not _stack_redraw_invalidated
        and not size_changed
        and len(previous_lines) == len(lines)
    )
    can_rewrite_full_footprint = (
        previous_count > 0
        and (_cursor_positioned_above_stack or _cursor_positioned_on_stack_top)
        and len(previous_lines) == len(lines)
        and (_stack_redraw_invalidated or size_changed)
    )

    if lines and can_diff_redraw:
        changed_indexes = [
            index for index, (old_line, new_line) in enumerate(zip(previous_lines, lines))
            if old_line != new_line
        ]

        if changed_indexes:
            base_offset = 1 if _cursor_positioned_above_stack else 0
            for index in changed_indexes:
                offset = index + base_offset
                if offset > 0:
                    sequences.append(f'\033[{offset}B')
                sequences.append('\r')
                sequences.append('\033[2K')
                sequences.append(lines[index])
                sequences.append('\r')
                if offset > 0:
                    sequences.append(f'\033[{offset}A')

            _write(''.join(sequences))
            _flush_stream()

        _last_drawn_progress_count = len(lines)
        _last_rendered_terminal_size = (terminal_columns, terminal_rows)
        _last_rendered_progress_lines = list(lines)
        _set_stack_cursor_anchor(len(lines), terminal_rows)
        _stack_redraw_invalidated = False
        _set_cursor_visibility_locked(False, backend_state=state)
        with _STATE_LOCK:
            _dirty_progress_bars.difference_update(bars)
        _record_progress_activity_locked()
        return

    if lines and can_rewrite_full_footprint:
        base_offset = 1 if _cursor_positioned_above_stack else 0
        for index, line in enumerate(lines):
            offset = index + base_offset
            if offset > 0:
                sequences.append(f'\033[{offset}B')
            sequences.append('\r')
            sequences.append('\033[2K')
            sequences.append(line)
            sequences.append('\r')
            if offset > 0:
                sequences.append(f'\033[{offset}A')

        _write(''.join(sequences))
        _flush_stream()

        _last_drawn_progress_count = len(lines)
        _last_rendered_terminal_size = (terminal_columns, terminal_rows)
        _last_rendered_progress_lines = list(lines)
        _set_stack_cursor_anchor(len(lines), terminal_rows)
        _stack_redraw_invalidated = False
        _set_cursor_visibility_locked(False, backend_state=state)
        with _STATE_LOCK:
            _dirty_progress_bars.difference_update(bars)
        _record_progress_activity_locked()
        return

    if previous_count:
        if _cursor_positioned_above_stack:
            sequences.append('\033[1B')
        elif _cursor_positioned_on_stack_top:
            sequences.append('\r')
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
        _last_rendered_terminal_size = (terminal_columns, terminal_rows)
        _last_rendered_progress_lines = []
        _cursor_positioned_above_stack = False
        _stack_redraw_invalidated = False
        _set_cursor_visibility_locked(True, backend_state=state)
        with _STATE_LOCK:
            _dirty_progress_bars.difference_update(bars)
        _record_progress_activity_locked()
        return

    for idx, line in enumerate(lines):
        sequences.append('\r')
        sequences.append(line)
        if idx < len(lines) - 1:
            sequences.append('\n')

    sequences.append('\r')
    move_up = len(lines)
    if terminal_rows > 0 and len(lines) >= terminal_rows:
        move_up = max(0, len(lines) - 1)
    if move_up > 0:
        sequences.append(f'\033[{move_up}A')

    _write(''.join(sequences))
    _flush_stream()
    _last_drawn_progress_count = len(lines)
    _last_rendered_terminal_size = (terminal_columns, terminal_rows)
    _last_rendered_progress_lines = list(lines)
    _set_stack_cursor_anchor(len(lines), terminal_rows)
    _stack_redraw_invalidated = False
    _set_cursor_visibility_locked(False, backend_state=state)
    with _STATE_LOCK:
        _dirty_progress_bars.difference_update(bars)
    _record_progress_activity_locked()


def render_progress_stack(
    lock_held: bool = False,
    precomputed: Optional[dict] = None,
    columns_hint: Optional[int] = None,
    backend_state: Optional[RenderBackendState] = None,
) -> None:
    """Redraw all attached progress bars respecting their attach order."""

    if lock_held:
        _render_progress_stack_locked(precomputed=precomputed, columns_hint=columns_hint, backend_state=backend_state)
    else:
        with _RENDER_LOCK:
            _render_progress_stack_locked(precomputed=precomputed, columns_hint=columns_hint, backend_state=backend_state)


def _record_progress_activity_locked() -> None:
    global _last_active_draw
    _last_active_draw = time.monotonic()


def _record_progress_activity() -> None:
    with _STATE_LOCK:
        _record_progress_activity_locked()


def _should_refresh_in_background(state: RenderBackendState, bars: Sequence["ProgressBar"]) -> bool:
    if state.supports_cursor or state.notebook:
        return True

    for pb in bars:
        if callable(getattr(pb, "_tick_background_refresh", None)):
            return True

    return False


def _progress_refresh_worker() -> None:
    while True:
        time.sleep(_REFRESH_INTERVAL_SECONDS)

        with _STATE_LOCK:
            has_progress = bool(_attached_progress_bars)

        if not has_progress:
            continue

        try:
            state = _current_render_backend_state()
        except Exception:
            continue

        if not _RENDER_LOCK.acquire(blocking=False):
            continue

        try:
            bars = _active_progress_bars()
            if not bars:
                continue

            if not _should_refresh_in_background(state, bars):
                continue

            now = time.monotonic()
            precomputed = {}
            for pb in bars:
                tick = getattr(pb, "_tick_background_refresh", None)
                if not callable(tick) or not tick(now):
                    continue

                resolve_rendered = getattr(pb, "_resolve_rendered_line", None)
                if callable(resolve_rendered):
                    rendered = _call_resolve_rendered_line(
                        resolve_rendered,
                        state.columns,
                        force=True,
                        allow_repeat=True,
                        backend_state=state,
                    )
                    precomputed[pb] = rendered if rendered is not None else (pb._last_rendered_line or "")

            size_changed = state.supports_cursor and _last_rendered_terminal_size != (state.columns, state.lines)
            if not precomputed and not size_changed:
                continue

            _render_progress_stack_locked(
                precomputed=precomputed or None,
                columns_hint=state.columns,
                backend_state=state,
            )
        except Exception:
            continue
        finally:
            _RENDER_LOCK.release()


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

LEVEL_TO_LOGGING = {
    LEVEL.DEBUG: logging.DEBUG,
    LEVEL.INFO: logging.INFO,
    LEVEL.WARN: logging.WARNING,
    LEVEL.ERROR: logging.ERROR,
    LEVEL.CRITICAL: logging.CRITICAL,
}

LEVEL_NAME_TO_LOGGING = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRIT": logging.CRITICAL,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
    "NOTSET": logging.NOTSET,
}

LOGGING_TO_LEVEL_LABEL = {
    logging.DEBUG: LEVEL.DEBUG.value,
    logging.INFO: LEVEL.INFO.value,
    logging.WARNING: LEVEL.WARN.value,
    logging.ERROR: LEVEL.ERROR.value,
    logging.CRITICAL: LEVEL.CRITICAL.value,
}

class LogBar(logging.Logger):
    NOTSET = logging.NOTSET
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARN = logging.WARNING
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL
    FATAL = logging.CRITICAL

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


    def pb(self, iterable: Iterable, *, output_interval: Optional[int] = None):
        from logbar.progress import ProgressBar

        return ProgressBar(iterable, owner=self, output_interval=output_interval).attach(self)

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

    def _normalize_level(self, level: Union[LEVEL, int, str]) -> int:
        if isinstance(level, LEVEL):
            return LEVEL_TO_LOGGING[level]

        if isinstance(level, int):
            return level

        if isinstance(level, str):
            normalized = level.strip().upper()
            if not normalized:
                raise ValueError("Log level must not be empty.")

            if normalized in LEVEL_NAME_TO_LOGGING:
                return LEVEL_NAME_TO_LOGGING[normalized]

            numeric = normalized
            if normalized.startswith(("+", "-")):
                numeric = normalized[1:]

            if numeric.isdigit():
                return int(normalized)

            raise ValueError(f"Unknown log level: {level!r}")

        raise TypeError(
            "Log level must be a LEVEL enum, integer, or string name."
        )

    def _level_label(self, level: Union[LEVEL, int, str], normalized_level: int) -> str:
        if isinstance(level, LEVEL):
            return level.value

        if isinstance(level, str):
            normalized = level.strip().upper()
            if normalized in ("WARNING", "WARN"):
                return LEVEL.WARN.value
            if normalized in ("CRITICAL", "FATAL", "CRIT"):
                return LEVEL.CRITICAL.value
            if normalized in ("DEBUG", "INFO", "ERROR"):
                return normalized

        return LOGGING_TO_LEVEL_LABEL.get(
            normalized_level,
            str(logging.getLevelName(normalized_level)),
        )

    def setLevel(self, level: Union[LEVEL, int, str]) -> None:
        """Set the per-instance minimum output threshold for LogBar methods."""

        super().setLevel(self._normalize_level(level))

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

    def _emit_log_line_locked(
        self,
        normalized_level: int,
        level_label: str,
        str_msg: str,
        *,
        allow_defer: bool = True,
        backend_state: Optional[RenderBackendState] = None,
    ) -> None:
        global last_rendered_length, _cursor_positioned_above_stack, _deferred_log_records

        backend_state = backend_state or _current_render_backend_state()
        columns = backend_state.columns
        terminal_rows = backend_state.lines
        level_width = max(LEVEL_MAX_LENGTH, len(level_label))

        with _STATE_LOCK:
            previous_render_length = last_rendered_length

        message_width = visible_length(str_msg)
        line_length = level_width + 1 + message_width

        if columns > 0:
            padding_needed = max(0, columns - level_width - 2 - message_width)
            rendered_message = f"{str_msg}{' ' * padding_needed}"
            printable_length = columns
        else:
            printable_length = line_length
            excess_padding = max(0, previous_render_length - printable_length)
            rendered_message = f"{str_msg}{' ' * excess_padding}" if excess_padding else str_msg

        if allow_defer and _should_defer_log_output_locked(terminal_rows):
            _deferred_log_records.append((normalized_level, str_msg))
            return

        stacked_log_insert = _prepare_progress_stack_for_log_locked()
        if not stacked_log_insert:
            _clear_progress_stack_locked(for_log_output=True)

        if backend_state.supports_ansi:
            reset = COLORS["RESET"]
            color = COLORS.get(level_label, reset)
        else:
            reset = ""
            color = ""
        level_padding = " " * (level_width - len(level_label))
        _print(f"\r{color}{level_label}{reset}{level_padding} {rendered_message}", end='\n', flush=True)

        with _STATE_LOCK:
            last_rendered_length = printable_length

        if stacked_log_insert:
            _write('\033[1A\r')
            _flush_stream()
            _cursor_positioned_above_stack = True

        _render_progress_stack_locked(backend_state=backend_state)

    def _process(self, level: Union[LEVEL, int, str], msg, *args, **kwargs):
        normalized_level = self._normalize_level(level)
        if not self.isEnabledFor(normalized_level):
            return

        level_label = self._level_label(level, normalized_level)
        str_msg = self._format_message(msg, args)

        with _RENDER_LOCK:
            backend_state = _current_render_backend_state()
            terminal_rows = backend_state.lines
            if _deferred_log_records and not _should_defer_log_output_locked(terminal_rows):
                _flush_deferred_logs_locked()

            self._emit_log_line_locked(
                normalized_level,
                level_label,
                str_msg,
                allow_defer=True,
                backend_state=backend_state,
            )
