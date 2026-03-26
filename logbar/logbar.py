# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import atexit
import builtins
import logging
import os
import sys
import threading
import time
from enum import Enum
from functools import lru_cache, wraps
from typing import Iterable, Optional, Sequence, Union, TYPE_CHECKING

from .terminal import RenderBackendState, render_backend_state, terminal_size
from .columns import ColumnSpec, ColumnsPrinter
from .buffer import get_buffered_stdout
from .coordinator import RenderCoordinator
from .drawing import ansi_to_html, strip_ansi, visible_length
from .region import LineRegion

# global static/shared logger instance
logger = None
last_rendered_length = 0

_STATE_LOCK = threading.RLock()
_RENDER_LOCK = threading.RLock()
_EXTERNAL_TERMINAL_HANDOFF_HOOKS_INSTALLED = False

def _stdout_stream():
    """Return the stdout stream wrapper used by all renderer writes."""

    return get_buffered_stdout(sys.stdout)


def _write(data: str) -> int:
    """Write raw text to the shared stdout wrapper."""

    stream = _stdout_stream()
    return stream.write(data)


def _flush_stream() -> None:
    """Flush the shared stdout wrapper when the backend exposes flush()."""

    stream = _stdout_stream()
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def _print(*args, **kwargs) -> None:
    """Print through the shared stdout wrapper with flush enabled by default."""

    if "file" not in kwargs:
        kwargs["file"] = _stdout_stream()
    kwargs.setdefault("flush", True)
    builtins.print(*args, **kwargs)

_notebook_display_handle = None
_notebook_plain_last_line: Optional[str] = None
_notebook_plain_last_width = 0


def _current_render_backend_state(columns_hint: Optional[int] = None) -> RenderBackendState:
    """Capture backend capabilities and size for the current stdout target."""

    notebook = _running_in_notebook_environment()

    if columns_hint is not None:
        def _size_provider():
            """Reuse the live row count while forcing a caller-supplied width."""

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
    """Best-effort check for cursor positioning support on stdout."""

    try:
        state = _current_render_backend_state()
    except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
        return False
    return state.supports_cursor


def _stdout_supports_ansi() -> bool:
    """Best-effort check for raw ANSI styling support on stdout."""

    try:
        state = _current_render_backend_state()
    except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
        return False
    return state.supports_ansi


def _notebook_render_stack(lines: Sequence[str]) -> bool:
    """Render the stack using IPython display machinery when available."""

    global _notebook_display_handle, _notebook_plain_last_line, _notebook_plain_last_width

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
            _notebook_plain_last_line = None
            _notebook_plain_last_width = 0
    except Exception:
        _notebook_display_handle = None
        return False

    return True


def _notebook_render_plain_stdout(lines: Sequence[str], *, strip_styles: bool = False) -> None:
    """Fallback notebook-friendly rendering using carriage returns only."""

    global _notebook_plain_last_line, _notebook_plain_last_width

    if strip_styles:
        lines = [strip_ansi(line) for line in lines]

    if not lines:
        if _notebook_plain_last_line is not None:
            _write('\r')
            _write(' ' * _notebook_plain_last_width)
            _write('\r')
            _flush_stream()
        _notebook_plain_last_line = None
        _notebook_plain_last_width = 0
        return

    joined = '\n'.join(lines)

    if len(lines) == 1:
        joined_width = visible_length(joined)
        pad = _notebook_plain_last_width - joined_width
        _write('\r')
        _write(joined)
        if pad > 0:
            _write(' ' * pad)
        _flush_stream()
        _notebook_plain_last_line = joined
        _notebook_plain_last_width = joined_width
        return

    # We cannot reposition multiple lines reliably without cursor controls. Emit the block once.
    _write('\r')
    _write(joined)
    _flush_stream()
    _notebook_plain_last_line = lines[-1]
    _notebook_plain_last_width = visible_length(lines[-1])

def render_lock() -> threading.RLock:
    """Provide access to the shared render lock used for stdout writes."""

    return _RENDER_LOCK

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from .progress import ProgressBar

def _sync_default_coordinator_state() -> None:
    """Mirror coordinator-owned state onto legacy module globals for compatibility."""

    state = _DEFAULT_RENDER_COORDINATOR.state
    for field_name in state.field_names():
        globals()[field_name] = getattr(state, field_name)


def _coordinator_state():
    """Return the mutable state object backing the default render coordinator."""

    return _DEFAULT_RENDER_COORDINATOR.state


_DEFAULT_RENDER_COORDINATOR = RenderCoordinator(
    on_state_change=lambda _name, _value: _sync_default_coordinator_state()
)
_ROOT_STACK_REGION = LineRegion(vertical_anchor="bottom")
_DEFAULT_RENDER_COORDINATOR.register_region(_DEFAULT_RENDER_COORDINATOR.root_region_id, _ROOT_STACK_REGION)
_sync_default_coordinator_state()
_REFRESH_INTERVAL_SECONDS = 0.1


def _running_under_pytest() -> bool:
    """Best-effort detection for pytest-driven terminal sessions."""

    argv0 = os.path.basename(str(sys.argv[0])).lower()
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in argv0


def _install_external_terminal_handoff_hooks() -> None:
    """Install framework-specific terminal handoff hooks when available.

    The underlying problem is not pytest-specific: any framework that writes
    directly to the terminal while LogBar still owns a bottom footer can land
    output inside the footer footprint while the cursor is hidden and parked at
    the stack anchor. Pytest is the concrete case we reproduced because it
    prints `PASSED` and the warnings summary after the test body has already
    returned, outside LogBar's normal log path.
    """

    global _EXTERNAL_TERMINAL_HANDOFF_HOOKS_INSTALLED

    if _EXTERNAL_TERMINAL_HANDOFF_HOOKS_INSTALLED:
        return

    _install_pytest_terminal_handoff_adapter()
    _EXTERNAL_TERMINAL_HANDOFF_HOOKS_INSTALLED = True


def _install_pytest_terminal_handoff_adapter() -> None:
    """Teach pytest to hand the terminal back before it writes session output."""

    if not _running_under_pytest():
        return

    try:
        from _pytest.terminal import TerminalReporter
    except Exception:
        TerminalReporter = None

    try:
        from _pytest._io.terminalwriter import TerminalWriter
    except Exception:
        TerminalWriter = None

    def _wrap_method(method_name: str) -> None:
        if TerminalReporter is None:
            return
        original = getattr(TerminalReporter, method_name, None)
        if not callable(original) or getattr(original, "_logbar_terminal_handoff_wrapped", False):
            return

        @wraps(original)
        def _wrapped(self, *args, **kwargs):
            # Observed failure: pytest would print `PASSED` or the warnings
            # summary while LogBar still had a live stacked footer. That
            # foreign write bypasses LogBar's own log-above-stack path, so we
            # must explicitly release the footer before pytest writes.
            if _coordinator_state()._last_drawn_progress_count > 0:
                try:
                    _shutdown_default_renderer()
                except Exception:
                    pass
            return original(self, *args, **kwargs)

        setattr(_wrapped, "_logbar_terminal_handoff_wrapped", True)
        setattr(TerminalReporter, method_name, _wrapped)

    def _wrap_writer_method(method_name: str) -> None:
        if TerminalWriter is None:
            return

        original = getattr(TerminalWriter, method_name, None)
        if not callable(original) or getattr(original, "_logbar_terminal_handoff_wrapped", False):
            return

        @wraps(original)
        def _wrapped(self, *args, **kwargs):
            # `write_raw()` is the last common sink before bytes hit the
            # terminal. Wrapping it catches pytest output paths that bypass the
            # higher-level reporter helpers.
            if _coordinator_state()._last_drawn_progress_count > 0:
                try:
                    _shutdown_default_renderer()
                except Exception:
                    pass
            return original(self, *args, **kwargs)

        setattr(_wrapped, "_logbar_terminal_handoff_wrapped", True)
        setattr(TerminalWriter, method_name, _wrapped)

    for method_name in ("write", "line", "write_line", "rewrite", "write_sep"):
        _wrap_method(method_name)
    _wrap_writer_method("write_raw")


def _set_stack_cursor_anchor(line_count: int, terminal_rows: int) -> None:
    """Record whether the cursor is parked above the stack or on its top row."""

    state = _coordinator_state()

    if line_count <= 0:
        state._cursor_positioned_above_stack = False
        state._cursor_positioned_on_stack_top = False
        return

    if terminal_rows > 0 and line_count >= terminal_rows:
        state._cursor_positioned_above_stack = False
        state._cursor_positioned_on_stack_top = True
        return

    state._cursor_positioned_above_stack = True
    state._cursor_positioned_on_stack_top = False


def _should_defer_log_output_locked(terminal_rows: int) -> bool:
    """Decide whether fullscreen stacks must buffer logs until they clear."""

    state = _coordinator_state()

    if state._last_drawn_progress_count <= 0:
        return False

    if terminal_rows <= 0:
        return False

    return (
        state._last_drawn_progress_count >= terminal_rows
        and not state._cursor_positioned_above_stack
    )


def _flush_deferred_logs_locked() -> None:
    """Replay log lines buffered while the stack occupied the full terminal."""

    state = _coordinator_state()

    if not state._deferred_log_records or logger is None:
        return

    pending = list(state._deferred_log_records)
    state._deferred_log_records = []

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
        _DEFAULT_RENDER_COORDINATOR.attach_progress_bar(pb)
        _record_progress_activity_locked()
    _ensure_background_refresh_thread()


def detach_progress_bar(pb: "ProgressBar") -> None:
    """Stop managing a progress bar."""

    with _STATE_LOCK:
        _DEFAULT_RENDER_COORDINATOR.detach_progress_bar(pb)
        _record_progress_activity_locked()


def mark_progress_bar_dirty(pb: "ProgressBar") -> None:
    """Mark an attached progress bar for the next stack redraw."""

    with _STATE_LOCK:
        _DEFAULT_RENDER_COORDINATOR.mark_progress_bar_dirty(pb)
        _record_progress_activity_locked()


def _set_cursor_visibility_locked(visible: bool, backend_state: Optional[RenderBackendState] = None) -> None:
    """Toggle the terminal cursor visibility, avoiding redundant writes."""

    state = backend_state
    if state is None:
        try:
            state = _current_render_backend_state()
        except Exception:  # pragma: no cover - keep rendering alive on odd stdouts
            state = None

    if state is None or not state.supports_cursor:
        _coordinator_state()._cursor_hidden = False
        return

    hidden = not visible
    coordinator_state = _coordinator_state()
    if coordinator_state._cursor_hidden == hidden:
        return

    code = '\033[?25h' if visible else '\033[?25l'
    _print(code, end='')
    coordinator_state._cursor_hidden = hidden


def _clear_progress_stack_locked(
    *,
    show_cursor: bool = True,
    for_log_output: bool = False,
    flush_deferred_logs: bool = True,
    backend_state: Optional[RenderBackendState] = None,
) -> None:
    """Erase the active stack and reset all renderer bookkeeping.

    `flush_deferred_logs` is normally enabled so fullscreen stacks replay any
    buffered log lines after the footer clears. Shutdown paths disable it
    because, during interpreter teardown, replaying deferred logs can create
    fresh writes after we just released terminal ownership.
    """

    coordinator_state = _coordinator_state()
    count = coordinator_state._last_drawn_progress_count
    state = backend_state or _current_render_backend_state()
    supports_cursor = state.supports_cursor

    if not supports_cursor:
        if not _notebook_render_stack([]):
            _notebook_render_plain_stdout([], strip_styles=state.notebook)
        coordinator_state._last_drawn_progress_count = 0
        coordinator_state._last_rendered_terminal_size = None
        coordinator_state._last_rendered_progress_lines = []
        coordinator_state._cursor_positioned_above_stack = False
        coordinator_state._cursor_positioned_on_stack_top = False
        coordinator_state._stack_redraw_invalidated = False
        if show_cursor:
            _set_cursor_visibility_locked(True, backend_state=state)
        if flush_deferred_logs and not for_log_output:
            _flush_deferred_logs_locked()
        return

    if count == 0:
        coordinator_state._last_rendered_terminal_size = None
        coordinator_state._last_rendered_progress_lines = []
        coordinator_state._cursor_positioned_above_stack = False
        coordinator_state._cursor_positioned_on_stack_top = False
        coordinator_state._stack_redraw_invalidated = False
        if show_cursor:
            _set_cursor_visibility_locked(True, backend_state=state)
        if flush_deferred_logs and not for_log_output:
            _flush_deferred_logs_locked()
        return

    sequences: list[str] = []

    # Reposition to the stack anchor before clearing so both bottom-anchored
    # and fullscreen stacks erase the same footprint they last painted.
    if coordinator_state._cursor_positioned_above_stack:
        sequences.append('\033[1B')
    elif coordinator_state._cursor_positioned_on_stack_top:
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

    coordinator_state._last_drawn_progress_count = 0
    coordinator_state._last_rendered_terminal_size = None
    coordinator_state._last_rendered_progress_lines = []
    coordinator_state._cursor_positioned_above_stack = False
    coordinator_state._cursor_positioned_on_stack_top = False
    coordinator_state._stack_redraw_invalidated = False
    if show_cursor:
        _set_cursor_visibility_locked(True, backend_state=state)
    if flush_deferred_logs and not for_log_output:
        _flush_deferred_logs_locked()


def _write_exit_sequence(data: str) -> bool:
    """Write raw ANSI directly to the terminal file descriptors when possible.

    During late shutdown we observed that stdio wrappers can be partially torn
    down even though the controlling terminal still exists. Writing straight to
    the file descriptors, and finally `/dev/tty`, gives the cursor-restore
    sequence a better chance to land than going through buffered stdout.
    """

    if not data:
        return True

    payload = data.encode("utf-8", errors="ignore")
    for fd in (1, 2):
        try:
            os.write(fd, payload)
            return True
        except OSError:
            continue

    tty_fd = None
    try:
        tty_fd = os.open("/dev/tty", os.O_WRONLY)
        os.write(tty_fd, payload)
        return True
    except OSError:
        return False
    finally:
        if tty_fd is not None:
            try:
                os.close(tty_fd)
            except OSError:
                pass


def _clear_progress_stack_for_exit() -> None:
    """Clear the last known footer footprint without probing stdout again.

    This uses only the last recorded stack geometry. It exists for teardown
    scenarios where capability probes or normal stdout writes are no longer
    trustworthy, but we still need to erase the leaked footer and show the
    cursor before the process exits.
    """

    coordinator_state = _coordinator_state()
    count = coordinator_state._last_drawn_progress_count
    sequences: list[str] = []

    if count > 0:
        if coordinator_state._cursor_positioned_above_stack:
            sequences.append('\033[1B')
        elif coordinator_state._cursor_positioned_on_stack_top:
            sequences.append('\r')
        else:
            sequences.append('\r')
            if count > 1:
                sequences.append(f'\033[{count - 1}A')

        sequences.append('\r')
        sequences.append('\033[J')

    sequences.append('\033[?25h')
    _write_exit_sequence(''.join(sequences))

    coordinator_state._last_drawn_progress_count = 0
    coordinator_state._last_rendered_terminal_size = None
    coordinator_state._last_rendered_progress_lines = []
    coordinator_state._cursor_positioned_above_stack = False
    coordinator_state._cursor_positioned_on_stack_top = False
    coordinator_state._stack_redraw_invalidated = False
    coordinator_state._cursor_hidden = False


def _shutdown_default_renderer() -> None:
    """Best-effort process-exit cleanup for leaked footer renderables.

    If a bar leaks past the end of a test or CLI command, LogBar can still own
    the terminal when some other code starts printing. The concrete reproduction
    was pytest emitting `PASSED` and its warnings summary above a live stacked
    footer, leaving the cursor hidden and the terminal in a bad state until
    `reset`. This shutdown path force-releases that ownership.
    """

    global last_rendered_length

    attached_bars = []
    backend_state = None
    cursor_was_hidden = False

    try:
        with _RENDER_LOCK:
            with _STATE_LOCK:
                coordinator_state = _coordinator_state()
                attached_bars = list(coordinator_state._attached_progress_bars)
                cursor_was_hidden = bool(coordinator_state._cursor_hidden)
                coordinator_state._attached_progress_bars = []
                coordinator_state._dirty_progress_bars.clear()
                coordinator_state._deferred_log_records = []
                coordinator_state._refresh_thread = None

            try:
                backend_state = _current_render_backend_state()
            except Exception:
                backend_state = None

            if backend_state is not None and backend_state.supports_cursor:
                try:
                    # Normal path: we can still talk to the terminal through
                    # the current stdout backend, so reuse the ordinary stack
                    # clear logic and explicitly show the cursor.
                    _clear_progress_stack_locked(
                        show_cursor=True,
                        flush_deferred_logs=False,
                        backend_state=backend_state,
                    )
                except Exception:
                    # Late-teardown fallback: rely on the last known stack
                    # state and write escape codes directly to the terminal.
                    _clear_progress_stack_for_exit()
            elif cursor_was_hidden or _coordinator_state()._last_drawn_progress_count > 0:
                _clear_progress_stack_for_exit()

            last_rendered_length = 0

            for bar in attached_bars:
                try:
                    setattr(bar, "_attached", False)
                    setattr(bar, "_attached_logger", None)
                    setattr(bar, "_last_rendered_line", "")
                except Exception:
                    continue
    except Exception:
        return


atexit.register(_shutdown_default_renderer)


def _prepare_progress_stack_for_log_locked(backend_state: Optional[RenderBackendState] = None) -> bool:
    """Write a log line above the active stack and force a full redraw afterward."""

    coordinator_state = _coordinator_state()
    count = coordinator_state._last_drawn_progress_count
    if count == 0:
        return False

    state = backend_state
    if state is None:
        try:
            state = _current_render_backend_state()
        except Exception:
            state = None

    if state is None or not state.supports_cursor:
        return False

    if not coordinator_state._cursor_positioned_above_stack:
        return False

    # The newline for the log line will briefly land on the first stack row.
    # Force the next stack paint to be a full redraw so any overwritten rows
    # are restored even when the frame contents are otherwise unchanged.
    coordinator_state._stack_redraw_invalidated = True
    return True


@lru_cache(maxsize=32)
def _level_prefix(level_label: str, supports_ansi: bool) -> str:
    """Build and cache the colored or plain log-level prefix."""

    level_width = max(LEVEL_MAX_LENGTH, len(level_label))
    level_padding = " " * (level_width - len(level_label))
    if not supports_ansi:
        return f"{level_label}{level_padding} "

    reset = COLORS["RESET"]
    color = COLORS.get(level_label, reset)
    return f"{color}{level_label}{reset}{level_padding} "


def _iter_contiguous_blocks(indexes: Sequence[int]):
    """Group sorted row indexes into contiguous rewrite blocks."""

    if not indexes:
        return

    start = indexes[0]
    end = start
    for index in indexes[1:]:
        if index == end + 1:
            end = index
            continue
        yield start, end
        start = index
        end = index
    yield start, end


def _rewrite_stack_rows(
    lines: Sequence[str],
    row_indexes: Sequence[int],
    *,
    cursor_above_stack: bool,
) -> str:
    """Rewrite specific stack rows while keeping the cursor at the anchor."""

    if not row_indexes:
        return ""

    base_offset = 1 if cursor_above_stack else 0
    sequences: list[str] = []

    for start, end in _iter_contiguous_blocks(row_indexes):
        offset = start + base_offset
        if offset > 0:
            sequences.append(f'\033[{offset}B')

        for index in range(start, end + 1):
            sequences.append('\r')
            sequences.append('\033[2K')
            sequences.append(lines[index])
            sequences.append('\r')
            if index < end:
                sequences.append('\033[1B')

        move_up = offset + (end - start)
        if move_up > 0:
            sequences.append(f'\033[{move_up}A')

    return ''.join(sequences)


def clear_progress_stack(lock_held: bool = False, backend_state: Optional[RenderBackendState] = None) -> None:
    """Erase any rendered progress bars from the terminal."""

    if lock_held:
        _clear_progress_stack_locked(backend_state=backend_state)
    else:
        with _RENDER_LOCK:
            _clear_progress_stack_locked(backend_state=backend_state)


def _active_progress_bars() -> list["ProgressBar"]:
    """Return a snapshot of bars currently attached to the shared stack."""

    with _STATE_LOCK:
        return _DEFAULT_RENDER_COORDINATOR.active_progress_bars()


def _call_resolve_rendered_line(
    resolve_rendered,
    columns: int,
    *,
    force: bool,
    allow_repeat: bool,
    backend_state: RenderBackendState,
) -> Optional[str]:
    """Call a bar's render resolver while tolerating older call signatures."""

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
    """Render the attached stack using diff redraws when possible."""

    coordinator_state = _coordinator_state()
    state = backend_state or _current_render_backend_state(columns_hint)
    columns = state.columns
    rows = state.lines

    bars = _active_progress_bars()
    with _STATE_LOCK:
        dirty_bars = set(coordinator_state._dirty_progress_bars)
    to_remove = []
    lines = []
    size_changed = coordinator_state._last_rendered_terminal_size != (max(0, int(columns)), max(0, int(rows)))

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
                _DEFAULT_RENDER_COORDINATOR.detach_progress_bar(pb)

    _ROOT_STACK_REGION.set_lines(lines)
    lines = _DEFAULT_RENDER_COORDINATOR.compose_root_lines(
        columns=columns,
        lines=rows,
        style_enabled=state.supports_styling,
    )

    supports_cursor = state.supports_cursor

    if not supports_cursor:
        handled = _notebook_render_stack(lines)
        if not handled:
            _notebook_render_plain_stdout(lines, strip_styles=state.notebook)
            _flush_stream()
        with _STATE_LOCK:
            coordinator_state._dirty_progress_bars.difference_update(bars)
        coordinator_state._last_drawn_progress_count = 0
        coordinator_state._last_rendered_terminal_size = None
        coordinator_state._last_rendered_progress_lines = []
        coordinator_state._cursor_positioned_above_stack = False
        coordinator_state._cursor_positioned_on_stack_top = False
        coordinator_state._stack_redraw_invalidated = False
        _set_cursor_visibility_locked(True, backend_state=state)
        _record_progress_activity_locked()
        return

    terminal_columns = max(0, int(columns))
    terminal_rows = max(0, int(rows))

    previous_count = coordinator_state._last_drawn_progress_count
    previous_lines = list(coordinator_state._last_rendered_progress_lines)
    sequences: list[str] = []

    can_diff_redraw = (
        previous_count > 0
        and (
            coordinator_state._cursor_positioned_above_stack
            or coordinator_state._cursor_positioned_on_stack_top
        )
        and not coordinator_state._stack_redraw_invalidated
        and not size_changed
        and len(previous_lines) == len(lines)
    )
    can_rewrite_full_footprint = (
        previous_count > 0
        and (
            coordinator_state._cursor_positioned_above_stack
            or coordinator_state._cursor_positioned_on_stack_top
        )
        and len(previous_lines) == len(lines)
        and (coordinator_state._stack_redraw_invalidated or size_changed)
    )

    if lines and can_diff_redraw:
        # Stable footprint: only touch rows whose rendered contents changed.
        changed_indexes = [
            index for index, (old_line, new_line) in enumerate(zip(previous_lines, lines))
            if old_line != new_line
        ]

        if changed_indexes:
            _write(
                _rewrite_stack_rows(
                    lines,
                    changed_indexes,
                    cursor_above_stack=coordinator_state._cursor_positioned_above_stack,
                )
            )
            _flush_stream()

        coordinator_state._last_drawn_progress_count = len(lines)
        coordinator_state._last_rendered_terminal_size = (terminal_columns, terminal_rows)
        coordinator_state._last_rendered_progress_lines = list(lines)
        _set_stack_cursor_anchor(len(lines), terminal_rows)
        coordinator_state._stack_redraw_invalidated = False
        _set_cursor_visibility_locked(False, backend_state=state)
        with _STATE_LOCK:
            coordinator_state._dirty_progress_bars.difference_update(bars)
        _record_progress_activity_locked()
        return

    if lines and can_rewrite_full_footprint:
        # Same row count but invalidated content or terminal geometry changed:
        # rewrite the whole footprint in place without clearing below it.
        _write(
            _rewrite_stack_rows(
                lines,
                list(range(len(lines))),
                cursor_above_stack=coordinator_state._cursor_positioned_above_stack,
            )
        )
        _flush_stream()

        coordinator_state._last_drawn_progress_count = len(lines)
        coordinator_state._last_rendered_terminal_size = (terminal_columns, terminal_rows)
        coordinator_state._last_rendered_progress_lines = list(lines)
        _set_stack_cursor_anchor(len(lines), terminal_rows)
        coordinator_state._stack_redraw_invalidated = False
        _set_cursor_visibility_locked(False, backend_state=state)
        with _STATE_LOCK:
            coordinator_state._dirty_progress_bars.difference_update(bars)
        _record_progress_activity_locked()
        return

    if previous_count:
        if coordinator_state._cursor_positioned_above_stack:
            sequences.append('\033[1B')
        elif coordinator_state._cursor_positioned_on_stack_top:
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
        coordinator_state._last_drawn_progress_count = 0
        coordinator_state._last_rendered_terminal_size = (terminal_columns, terminal_rows)
        coordinator_state._last_rendered_progress_lines = []
        coordinator_state._cursor_positioned_above_stack = False
        coordinator_state._stack_redraw_invalidated = False
        _set_cursor_visibility_locked(True, backend_state=state)
        with _STATE_LOCK:
            coordinator_state._dirty_progress_bars.difference_update(bars)
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
    coordinator_state._last_drawn_progress_count = len(lines)
    coordinator_state._last_rendered_terminal_size = (terminal_columns, terminal_rows)
    coordinator_state._last_rendered_progress_lines = list(lines)
    _set_stack_cursor_anchor(len(lines), terminal_rows)
    coordinator_state._stack_redraw_invalidated = False
    _set_cursor_visibility_locked(False, backend_state=state)
    with _STATE_LOCK:
        coordinator_state._dirty_progress_bars.difference_update(bars)
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
    """Update the last-seen progress activity timestamp."""

    _coordinator_state()._last_active_draw = time.monotonic()


def _record_progress_activity() -> None:
    """Thread-safe wrapper for bumping the progress activity timestamp."""

    with _STATE_LOCK:
        _record_progress_activity_locked()


def _should_refresh_in_background(state: RenderBackendState, bars: Sequence["ProgressBar"]) -> bool:
    """Return whether the background worker should wake for current bars."""

    if state.supports_cursor or state.notebook:
        return True

    for pb in bars:
        if callable(getattr(pb, "_tick_background_refresh", None)):
            return True

    return False


def _progress_refresh_worker() -> None:
    """Background loop that advances time-based renderables and resizes."""

    while True:
        time.sleep(_REFRESH_INTERVAL_SECONDS)

        with _STATE_LOCK:
            has_progress = bool(_coordinator_state()._attached_progress_bars)

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

                # Precompute refreshed frames while holding the same backend
                # snapshot so one tick does not race a second size probe.
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

            size_changed = (
                state.supports_cursor
                and _coordinator_state()._last_rendered_terminal_size != (state.columns, state.lines)
            )
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
    """Start the shared renderer refresh worker exactly once."""

    with _STATE_LOCK:
        state = _coordinator_state()
        if state._refresh_thread is not None and state._refresh_thread.is_alive():
            return

        thread = threading.Thread(
            target=_progress_refresh_worker,
            name="logbar-progress-refresh",
            daemon=True,
        )
        state._refresh_thread = thread
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
    """Canonical LogBar level labels used for output formatting."""

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
    """Logger subclass that multiplexes normal logs with live renderables."""

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
        """Return the process-wide shared LogBar instance."""

        global logger
        _install_external_terminal_handoff_hooks()

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
        """Create and attach a determinate progress bar owned by this logger."""

        from logbar.progress import ProgressBar

        return ProgressBar(iterable, owner=self, output_interval=output_interval).attach(self)

    def spinner(self, title: str = "", *, interval: float = 0.5, tail_length: int = 4):
        """Create and attach an indeterminate rolling spinner."""

        from logbar.progress import RollingProgressBar

        bar = RollingProgressBar(owner=self, interval=interval, tail_length=tail_length)
        if title:
            bar.title(title)
        return bar.attach(self)

    def history_add(self, msg) -> bool:
        """Track deduplicated messages for the `.once(...)` helpers."""

        h = hash(msg) # TODO only msg is checked not level + msg

        with self._history_lock:
            if h in self.history:
                return False # add failed since it already exists

            if len(self.history) > self.history_limit:
                self.history.clear()

            self.history.add(h)

        return True

    class critical_cls:
        """Proxy object that preserves legacy `log.critical.once(...)` calls."""

        def __init__(self, logger):
            """Bind the proxy to its owning logger instance."""

            self.logger = logger

        def once(self, msg, *args, **kwargs):
            """Emit the message only if it has not been seen before."""

            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            """Dispatch a critical message through the logger pipeline."""

            self.logger._process(LEVEL.CRITICAL, msg, *args, **kwargs)

    class warn_cls:
        """Proxy object that preserves legacy `log.warn.once(...)` calls."""

        def __init__(self, logger):
            """Bind the proxy to its owning logger instance."""

            self.logger = logger

        def once(self, msg, *args, **kwargs):
            """Emit the message only if it has not been seen before."""

            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            """Dispatch a warning message through the logger pipeline."""

            self.logger._process(LEVEL.WARN, msg, *args, **kwargs)

    class debug_cls:
        """Proxy object that preserves legacy `log.debug.once(...)` calls."""

        def __init__(self, logger):
            """Bind the proxy to its owning logger instance."""

            self.logger = logger

        def once(self, msg, *args, **kwargs):
            """Emit the message only if it has not been seen before."""

            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            """Dispatch a debug message through the logger pipeline."""

            self.logger._process(LEVEL.DEBUG, msg, *args, **kwargs)

    class info_cls:
        """Proxy object that preserves legacy `log.info.once(...)` calls."""

        def __init__(self, logger):
            """Bind the proxy to its owning logger instance."""

            self.logger = logger

        def once(self, msg, *args, **kwargs):
            """Emit the message only if it has not been seen before."""

            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            """Dispatch an info message through the logger pipeline."""

            self.logger._process(LEVEL.INFO, msg, *args, **kwargs)

    class error_cls:
        """Proxy object that preserves legacy `log.error.once(...)` calls."""

        def __init__(self, logger):
            """Bind the proxy to its owning logger instance."""

            self.logger = logger

        def once(self, msg, *args, **kwargs):
            """Emit the message only if it has not been seen before."""

            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            """Dispatch an error message through the logger pipeline."""

            self.logger._process(LEVEL.ERROR, msg, *args, **kwargs)

    def __init__(self, name):
        """Initialize the logger and install the legacy level proxies."""

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
        """Normalize enum, string, or numeric levels to stdlib integers."""

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
        """Resolve the display label used in the rendered log prefix."""

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
            """Consume the longest prefix of args that satisfies one format string."""

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
        """Emit one log line while preserving any active progress stack."""

        coordinator_state = _coordinator_state()
        global last_rendered_length

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
            coordinator_state._deferred_log_records.append((normalized_level, str_msg))
            return

        # Preserve terminal history when logs arrive above an active bottom
        # stack: clear the live footer using the log-output path before
        # printing, instead of parking on the same row and rewriting it.
        _clear_progress_stack_locked(
            show_cursor=False,
            for_log_output=True,
            backend_state=backend_state,
        )

        prefix = _level_prefix(level_label, backend_state.supports_ansi)
        _print(f"\r{prefix}{rendered_message}", end='\n', flush=True)

        with _STATE_LOCK:
            last_rendered_length = printable_length

        _render_progress_stack_locked(backend_state=backend_state)

    def _process(self, level: Union[LEVEL, int, str], msg, *args, **kwargs):
        """Shared implementation for all public logging entry points."""

        normalized_level = self._normalize_level(level)
        if not self.isEnabledFor(normalized_level):
            return

        level_label = self._level_label(level, normalized_level)
        str_msg = self._format_message(msg, args)

        with _RENDER_LOCK:
            backend_state = _current_render_backend_state()
            terminal_rows = backend_state.lines
            if _coordinator_state()._deferred_log_records and not _should_defer_log_output_locked(terminal_rows):
                _flush_deferred_logs_locked()

            self._emit_log_line_locked(
                normalized_level,
                level_label,
                str_msg,
                allow_defer=True,
                backend_state=backend_state,
            )
