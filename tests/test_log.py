# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import io
import logging
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import textwrap
from contextlib import redirect_stdout
import unittest
from unittest import mock


from logbar import LogBar
from logbar.buffer import QueueingStdout, get_buffered_stdout

log = LogBar.shared(override_logger=True)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def extract_rendered_lines(buffer: str):
    """Split captured terminal output into visible lines without ANSI escapes."""

    cleaned = ANSI_ESCAPE_RE.sub('', buffer)
    lines = []
    accumulator = []

    for char in cleaned:
        if char in ('\r', '\n'):
            if accumulator:
                lines.append(''.join(accumulator))
                accumulator = []
        else:
            accumulator.append(char)

    if accumulator:
        lines.append(''.join(accumulator))

    return [line for line in lines if line]


class TestProgressBar(unittest.TestCase):
    """Regression coverage for logger/progress stack interactions."""

    def capture_log(self, callable_, *args, **kwargs):
        """Capture stdout produced by one logging call."""

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            callable_(*args, **kwargs)
        return buffer.getvalue()

    def test_log_simple(self):
        """Emit a basic log line through the shared logger."""

        log.info("hello info")

    def test_log_once(self):
        """Suppress duplicate messages through the `.once()` helper."""

        log.info.once("hello info 1")
        log.info.once("hello info 1")

    def test_levels(self):
        """Exercise all custom level helpers once."""

        log.info("hello info")
        log.debug("hello debug")
        log.warn("hello warn")
        log.error("hello error")
        log.critical("hello critical")

    def test_set_level_string_filters_custom_helpers(self):
        """Honor string log levels when filtering custom helper methods."""

        local_log = LogBar("test_set_level_string_filters_custom_helpers")
        local_log.setLevel("ERROR")

        def emit():
            """Emit a mix of levels so filtering can be asserted."""

            local_log.debug("debug hidden token")
            local_log.info("info hidden token")
            local_log.error("error visible token")

        output = self.capture_log(emit)
        self.assertIn("error visible token", output)
        self.assertNotIn("debug hidden token", output)
        self.assertNotIn("info hidden token", output)

    def test_set_level_filters_custom_helpers(self):
        """Honor stdlib numeric log levels for custom helper methods."""

        local_log = LogBar("test_set_level_filters_custom_helpers")
        local_log.setLevel(logging.WARNING)

        def emit():
            """Emit info and warn lines under a warning threshold."""

            local_log.info("info hidden by setLevel")
            local_log.warn("warn visible by setLevel")

        output = self.capture_log(emit)
        self.assertIn("warn visible by setLevel", output)
        self.assertNotIn("info hidden by setLevel", output)

    def test_set_level_logbar_warning_alias_filters_custom_helpers(self):
        """Treat `LogBar.WARNING` as an alias for `logging.WARNING`."""

        local_log = LogBar("test_set_level_logbar_warning_alias_filters_custom_helpers")
        self.assertEqual(LogBar.WARNING, logging.WARNING)
        local_log.setLevel(LogBar.WARNING)

        def emit():
            """Emit info and warn lines under the LogBar warning alias."""

            local_log.info("info hidden by LogBar.WARNING")
            local_log.warn("warn visible by LogBar.WARNING")

        output = self.capture_log(emit)
        self.assertIn("warn visible by LogBar.WARNING", output)
        self.assertNotIn("info hidden by LogBar.WARNING", output)

    def test_set_level_rejects_unknown_names(self):
        """Reject unsupported symbolic level names with a clear error."""

        local_log = LogBar("test_set_level_rejects_unknown_names")
        with self.assertRaises(ValueError):
            local_log.setLevel("TRACE")

    def test_log_without_terminal_state(self):
        """LogBar should operate even when the runtime lacks a terminal."""

        stdout = io.StringIO()

        with mock.patch('sys.stdout', stdout), \
             mock.patch('logbar.terminal.shutil.get_terminal_size', side_effect=OSError()), \
             mock.patch.dict('logbar.terminal.os.environ', {}, clear=True):
            log.info("logging without terminal")

        # The log output should have been written to the patched stdout buffer.
        self.assertIn("logging without terminal", stdout.getvalue())

    def test_log_plain_stream_omits_ansi_sequences(self):
        """Avoid leaking ANSI prefixes when stdout is not a TTY."""

        stdout = io.StringIO()

        with mock.patch('sys.stdout', stdout), \
             mock.patch.dict('logbar.terminal.os.environ', {}, clear=True):
            log.info("plain stream log")

        output = stdout.getvalue()
        self.assertIn("plain stream log", output)
        self.assertNotIn("\033[", output)

    def test_percent_formatting(self):
        """Support classic printf-style formatting with one positional arg."""

        output = self.capture_log(log.info, "%d", 123)
        self.assertIn("123", output)

    def test_percent_formatting_multiple_args(self):
        """Support a range of `%`-formatting patterns and argument shapes."""

        cases = [
            ("Numbers: %d %d %d", (1, 2, 3)),
            ("Signed and padded: %+d %05d", (42, 7)),
            ("Floats: %.2f %.1f", (3.14159, 2.5)),
            ("Mapping: %(name)s => %(value)04d", ({"name": "counter", "value": 12},)),
            ("Literal percent %% and value %d%%", (88,)),
        ]

        for fmt, args in cases:
            output = self.capture_log(log.info, fmt, *args)

            fmt_args = args
            if len(args) == 1 and isinstance(args[0], dict):
                fmt_args = args[0]

            expected = fmt % fmt_args
            self.assertIn(expected, output)

    def test_argument_variants(self):
        """Support mixed formatting and plain argument concatenation cases."""

        cases = [
            (("simple string",), "simple string"),
            (("formated string %d", 123), "formated string 123"),
            (("multiple args %d, %s", 123, "hello"), "multiple args 123, hello"),
            (("multiple args %d", 123, "arg2 %s", "hello"), "multiple args 123 arg2 hello"),
            (("append output", "output2", "output3"), "append output output2 output3"),
        ]

        for args, expected in cases:
            with self.subTest(args=args):
                output = self.capture_log(log.info, *args)
                self.assertIn(expected, output)

    def test_concurrent_logging_thread_safe(self):
        """Serialize concurrent log writers without dropping messages."""

        thread_count = 5
        iterations = 20
        barrier = threading.Barrier(thread_count)

        def worker(thread_idx: int) -> None:
            """Synchronize thread start so concurrent logging overlaps heavily."""

            barrier.wait()
            for i in range(iterations):
                log.info(f"thread-{thread_idx}-{i}")

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(thread_count)]

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
        message_lines = [line for line in lines if "thread-" in line]

        self.assertEqual(len(message_lines), thread_count * iterations)
        for line in message_lines:
            self.assertIn("thread-", line)

    def test_stdout_wrapped_when_unbuffered(self):
        """Wrap unbuffered-like streams in the queueing stdout proxy."""

        class CollectingStream:
            """Collect writes while exposing the minimal stdout interface."""

            def __init__(self):
                """Initialize write history and thread metadata capture."""

                self._writes = []
                self._lock = threading.Lock()
                self.callers = []

            def write(self, data):
                """Record the write payload and the worker thread name."""

                with self._lock:
                    self._writes.append(data)
                    self.callers.append(threading.current_thread().name)
                return len(data)

            def flush(self):
                """No-op flush to satisfy the file-like contract."""

                return None

            def isatty(self):
                """Report a plain non-TTY stream."""

                return False

            def getvalue(self):
                """Return the concatenated captured output."""

                with self._lock:
                    return ''.join(self._writes)

        original_stdout = sys.stdout
        queue_stdout = None
        collector = CollectingStream()

        try:
            sys.stdout = collector
            log.info("buffered log")
            queue_stdout = get_buffered_stdout(collector)

            self.assertIsInstance(queue_stdout, QueueingStdout)
            queue_stdout.flush()
            self.assertIn("buffered log", collector.getvalue())
            self.assertIn("logbar-stdout-flush", collector.callers)
        finally:
            if queue_stdout is not None and getattr(queue_stdout, "_logbar_queue_wrapped", False):
                try:
                    queue_stdout.close()
                except Exception:
                    pass
            sys.stdout = original_stdout

    def test_logging_above_active_progress_stack_preserves_scroll_history(self):
        """Insert logs above a live stack using the scroll-preserving clear path."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 40
        stack_lines = [
            "top stack row".ljust(columns),
            "bottom stack row".ljust(columns),
        ]
        rows = [StaticRenderable(line) for line in stack_lines]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                log.info("stacked message")

            raw = buffer.getvalue()
            lines = extract_rendered_lines(raw)

            self.assertIn("\033[1S", raw)
            self.assertTrue(any("stacked message" in line for line in lines))
            for stack_line in stack_lines:
                self.assertIn(stack_line, lines)
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_logging_above_active_progress_stack_forces_full_redraw(self):
        """Restore the full stack after a log lands above it."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 32
        rows = [
            StaticRenderable("top row"),
            StaticRenderable("bottom row"),
        ]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                checkpoint = len(buffer.getvalue())
                log.info("message above stack")

            delta = buffer.getvalue()[checkpoint:]
            self.assertNotIn("\033[2K", delta)
            self.assertIn("\033[1S", delta)
            self.assertNotIn("\033[1L", delta)
            self.assertIn(rows[0].line.ljust(columns), ANSI_ESCAPE_RE.sub('', delta))
            self.assertIn(rows[1].line.ljust(columns), ANSI_ESCAPE_RE.sub('', delta))
            self.assertIn("message above stack", ANSI_ESCAPE_RE.sub('', delta))
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_fullscreen_progress_stack_defers_logs_until_clear(self):
        """Buffer logs when the stack already occupies the full terminal height."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 28
        terminal_rows = 2
        rows = [
            StaticRenderable("top row"),
            StaticRenderable("bottom row"),
        ]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, terminal_rows)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                checkpoint = len(buffer.getvalue())
                log.info("fullscreen message")
                active_delta = buffer.getvalue()[checkpoint:]

                for row in rows:
                    logbar_module.detach_progress_bar(row)
                logbar_module.clear_progress_stack()

            cleaned_active = ANSI_ESCAPE_RE.sub('', active_delta)
            cleaned_full = ANSI_ESCAPE_RE.sub('', buffer.getvalue())

            self.assertNotIn("\033[1S", active_delta)
            self.assertNotIn("fullscreen message", cleaned_active)
            self.assertIn("fullscreen message", cleaned_full)
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_progress_stack_reclips_after_terminal_resize(self):
        """Clip the visible stack to the newest terminal height after resize."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        current_size = [(28, 4)]
        rows = [StaticRenderable(f"row-{idx}-xxxxxxxxxxxxxxxx") for idx in range(5)]
        buffer = TTYBuffer()

        def terminal_size_provider():
            """Return the current mocked terminal size for the resize scenario."""

            return current_size[0]

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", side_effect=terminal_size_provider), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                current_size[0] = (18, 2)
                logbar_module.render_progress_stack()

            lines = extract_rendered_lines(buffer.getvalue())
            final_frame = lines[-2:]
            expected = [row.line[:18].ljust(18) for row in rows[-2:]]

            self.assertEqual(final_frame, expected)
            self.assertEqual(logbar_module._last_drawn_progress_count, 2)
            self.assertEqual(logbar_module._last_rendered_terminal_size, (18, 2))
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_progress_stack_skips_noop_redraw_for_identical_frame(self):
        """Avoid emitting terminal output when the stack frame is unchanged."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 32
        rows = [
            StaticRenderable("alpha-row"),
            StaticRenderable("beta-row"),
        ]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                checkpoint = len(buffer.getvalue())
                logbar_module.render_progress_stack()

            delta = buffer.getvalue()[checkpoint:]
            expected = [row.line[:columns].ljust(columns) for row in rows]

            self.assertEqual(delta, "")
            self.assertEqual(logbar_module._last_rendered_progress_lines, expected)
            self.assertEqual(logbar_module._last_drawn_progress_count, len(expected))
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_progress_stack_redraws_only_dirty_rows(self):
        """Rewrite only changed rows when the stack footprint is stable."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 36
        top_row = StaticRenderable("top-row")
        bottom_row = StaticRenderable("bottom-original")
        rows = [top_row, bottom_row]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                checkpoint = len(buffer.getvalue())
                bottom_row.line = "bottom-updated"
                logbar_module.render_progress_stack()

            delta = buffer.getvalue()[checkpoint:]
            cleaned_delta = ANSI_ESCAPE_RE.sub('', delta)
            expected = [row.line[:columns].ljust(columns) for row in rows]

            self.assertNotIn("\033[J", delta)
            self.assertIn("\033[2K", delta)
            self.assertNotIn(top_row.line, cleaned_delta)
            self.assertIn(bottom_row.line, cleaned_delta)
            self.assertEqual(logbar_module._last_rendered_progress_lines, expected)
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_progress_stack_groups_contiguous_dirty_rows_into_one_rewrite_block(self):
        """Coalesce adjacent dirty rows into one cursor-movement block."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 28
        rows = [
            StaticRenderable("row-0"),
            StaticRenderable("row-1"),
            StaticRenderable("row-2"),
        ]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                checkpoint = len(buffer.getvalue())
                rows[1].line = "row-1-updated"
                rows[2].line = "row-2-updated"
                logbar_module.render_progress_stack()

            delta = buffer.getvalue()[checkpoint:]
            cleaned_delta = ANSI_ESCAPE_RE.sub('', delta)

            self.assertIn(rows[1].line, cleaned_delta)
            self.assertIn(rows[2].line, cleaned_delta)
            self.assertEqual(delta.count("\033[2B"), 1)
            self.assertEqual(delta.count("\033[1B"), 1)
            self.assertEqual(delta.count("\033[3A"), 1)
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_progress_stack_uses_cached_lines_for_dirty_tracked_renderables(self):
        """Reuse cached lines for unchanged renderables that opt into dirty tracking."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class DirtyTrackedRenderable:
            """Renderable that records how often the renderer recomputes it."""

            def __init__(self, line: str):
                """Store the line content and enable dirty-tracking semantics."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""
                self._logbar_dirty_tracked = True
                self.render_calls = 0

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                self.render_calls += 1
                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 32
        top_row = DirtyTrackedRenderable("cached-top")
        bottom_row = DirtyTrackedRenderable("cached-bottom")
        rows = [top_row, bottom_row]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                self.assertEqual((top_row.render_calls, bottom_row.render_calls), (1, 1))

                checkpoint = len(buffer.getvalue())
                logbar_module.render_progress_stack()
                self.assertEqual((top_row.render_calls, bottom_row.render_calls), (1, 1))

                bottom_row.line = "cached-bottom-updated"
                logbar_module.mark_progress_bar_dirty(bottom_row)
                logbar_module.render_progress_stack()

            delta = buffer.getvalue()[checkpoint:]
            cleaned_delta = ANSI_ESCAPE_RE.sub('', delta)

            self.assertEqual(top_row.render_calls, 1)
            self.assertEqual(bottom_row.render_calls, 2)
            self.assertNotIn(top_row.line, cleaned_delta)
            self.assertIn(bottom_row.line, cleaned_delta)
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_shutdown_default_renderer_restores_cursor_for_leaked_stack(self):
        """Exit cleanup should show the cursor and clear leaked footer state."""

        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            """TTY-like capture stream used to keep cursor rendering enabled."""

            def isatty(self):
                """Pretend to be a TTY for the renderer under test."""

                return True

        class StaticRenderable:
            """Minimal stacked renderable that always returns one static line."""

            def __init__(self, line: str):
                """Store the line content and renderer bookkeeping fields."""

                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                """Render the stored line padded to the requested width."""

                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        columns = 32
        rows = [
            StaticRenderable("top row"),
            StaticRenderable("bottom row"),
        ]
        buffer = TTYBuffer()

        try:
            with mock.patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
                 mock.patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
                 mock.patch.object(logbar_module, "terminal_size", return_value=(columns, 24)), \
                 redirect_stdout(buffer):
                for row in rows:
                    logbar_module.attach_progress_bar(row)

                logbar_module.render_progress_stack()
                self.assertTrue(logbar_module._cursor_hidden)
                checkpoint = len(buffer.getvalue())
                logbar_module._shutdown_default_renderer()

            delta = buffer.getvalue()[checkpoint:]

            self.assertIn("\033[?25h", delta)
            self.assertFalse(logbar_module._cursor_hidden)
            self.assertEqual(logbar_module._last_drawn_progress_count, 0)
            self.assertEqual(logbar_module._attached_progress_bars, [])
        finally:
            with redirect_stdout(buffer):
                logbar_module._shutdown_default_renderer()

    def test_pytest_verbose_warning_summary_restores_cursor_on_process_exit(self):
        """A leaked live stack should not leave a PTY session with a hidden cursor."""

        script_bin = shutil.which("script")
        if script_bin is None:
            self.skipTest("`script` is required for PTY regression coverage.")
        pytest_bin = shutil.which("pytest")
        if pytest_bin is None:
            self.skipTest("`pytest` console entrypoint is required for PTY regression coverage.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            repro_path = temp_path / "pytest_warning_repro.py"
            transcript_path = temp_path / "pytest_warning_repro.typescript"

            repro_path.write_text(
                textwrap.dedent(
                    """
                    import time
                    import warnings

                    from logbar import LogBar


                    log = LogBar.shared(override_logger=True)
                    LEAKED = []


                    def test_warning_summary_with_leaked_live_stack():
                        spinner = log.spinner(title="rolling spinner", interval=0.02)
                        progress = log.pb(range(2)).title("top progress").manual()
                        LEAKED.extend((spinner, progress))

                        for idx in range(2):
                            progress.next()
                            progress.draw(force=True)
                            log.info("rolling log %s", idx + 1)
                            time.sleep(0.03)

                        warnings.warn("synthetic torchao deprecation", DeprecationWarning)
                        time.sleep(0.05)
                    """
                ),
                encoding="utf-8",
            )

            env = dict(os.environ)
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"/root/LogBar{os.pathsep}{existing_pythonpath}"
                if existing_pythonpath
                else "/root/LogBar"
            )

            command = f"{shlex.quote(pytest_bin)} -s -v {shlex.quote(str(repro_path))}"
            completed = subprocess.run(
                [script_bin, "-q", "-c", command, str(transcript_path)],
                cwd="/root/LogBar",
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
            hide_count = transcript.count("\x1b[?25l")
            show_count = transcript.count("\x1b[?25h")

            self.assertEqual(
                completed.returncode,
                0,
                msg=f"nested pytest run failed:\nstdout={completed.stdout}\nstderr={completed.stderr}\n{transcript}",
            )
            self.assertGreater(hide_count, 0)
            self.assertEqual(hide_count, show_count, msg=transcript)
