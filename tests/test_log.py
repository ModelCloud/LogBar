# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import io
import logging
import re
import sys
import threading
from contextlib import redirect_stdout
import unittest
from unittest import mock


from logbar import LogBar
from logbar.buffer import QueueingStdout, get_buffered_stdout

log = LogBar.shared(override_logger=True)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def extract_rendered_lines(buffer: str):
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

    def capture_log(self, callable_, *args, **kwargs):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            callable_(*args, **kwargs)
        return buffer.getvalue()

    def test_log_simple(self):
        log.info("hello info")

    def test_log_once(self):
        log.info.once("hello info 1")
        log.info.once("hello info 1")

    def test_levels(self):
        log.info("hello info")
        log.debug("hello debug")
        log.warn("hello warn")
        log.error("hello error")
        log.critical("hello critical")

    def test_set_level_string_filters_custom_helpers(self):
        local_log = LogBar("test_set_level_string_filters_custom_helpers")
        local_log.setLevel("ERROR")

        def emit():
            local_log.debug("debug hidden token")
            local_log.info("info hidden token")
            local_log.error("error visible token")

        output = self.capture_log(emit)
        self.assertIn("error visible token", output)
        self.assertNotIn("debug hidden token", output)
        self.assertNotIn("info hidden token", output)

    def test_set_level_filters_custom_helpers(self):
        local_log = LogBar("test_set_level_filters_custom_helpers")
        local_log.setLevel(logging.WARNING)

        def emit():
            local_log.info("info hidden by setLevel")
            local_log.warn("warn visible by setLevel")

        output = self.capture_log(emit)
        self.assertIn("warn visible by setLevel", output)
        self.assertNotIn("info hidden by setLevel", output)

    def test_set_level_logbar_warning_alias_filters_custom_helpers(self):
        local_log = LogBar("test_set_level_logbar_warning_alias_filters_custom_helpers")
        self.assertEqual(LogBar.WARNING, logging.WARNING)
        local_log.setLevel(LogBar.WARNING)

        def emit():
            local_log.info("info hidden by LogBar.WARNING")
            local_log.warn("warn visible by LogBar.WARNING")

        output = self.capture_log(emit)
        self.assertIn("warn visible by LogBar.WARNING", output)
        self.assertNotIn("info hidden by LogBar.WARNING", output)

    def test_set_level_rejects_unknown_names(self):
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

    def test_percent_formatting(self):
        output = self.capture_log(log.info, "%d", 123)
        self.assertIn("123", output)

    def test_percent_formatting_multiple_args(self):
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
        thread_count = 5
        iterations = 20
        barrier = threading.Barrier(thread_count)

        def worker(thread_idx: int) -> None:
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
        class CollectingStream:
            def __init__(self):
                self._writes = []
                self._lock = threading.Lock()
                self.callers = []

            def write(self, data):
                with self._lock:
                    self._writes.append(data)
                    self.callers.append(threading.current_thread().name)
                return len(data)

            def flush(self):
                return None

            def isatty(self):
                return False

            def getvalue(self):
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

    def test_logging_above_active_progress_stack_avoids_scroll_clear_path(self):
        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            def isatty(self):
                return True

        class StaticRenderable:
            def __init__(self, line: str):
                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
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

            self.assertIn("\033[1L", raw)
            self.assertNotIn("\033[1S", raw)
            self.assertTrue(any("stacked message" in line for line in lines))
            for stack_line in stack_lines:
                self.assertIn(stack_line, lines)
        finally:
            with redirect_stdout(buffer):
                logbar_module.clear_progress_stack()
            for row in rows:
                logbar_module.detach_progress_bar(row)

    def test_progress_stack_reclips_after_terminal_resize(self):
        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            def isatty(self):
                return True

        class StaticRenderable:
            def __init__(self, line: str):
                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
                rendered = self.line[:columns].ljust(columns)
                self._last_rendered_line = rendered
                return rendered

        current_size = [(28, 4)]
        rows = [StaticRenderable(f"row-{idx}-xxxxxxxxxxxxxxxx") for idx in range(5)]
        buffer = TTYBuffer()

        def terminal_size_provider():
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
        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            def isatty(self):
                return True

        class StaticRenderable:
            def __init__(self, line: str):
                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
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
        from logbar import logbar as logbar_module

        class TTYBuffer(io.StringIO):
            def isatty(self):
                return True

        class StaticRenderable:
            def __init__(self, line: str):
                self.line = line
                self.closed = False
                self._last_rendered_line = ""

            def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
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
