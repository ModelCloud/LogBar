# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from time import sleep
from unittest.mock import patch

from logbar import LogBar
from tests._stream_helpers import real_terminal_stream
from tests.test_snake_render import replay_terminal_screen


log = LogBar.shared(override_logger=True)


class TestProgressStack(unittest.TestCase):
    """Regression coverage for the default stacked progress-bar renderer."""

    def test_logs_and_stacked_progress_bars_coexist_without_vertical_overlap_for_five_seconds(self):
        """Keep a visible scrolling log history above the default stacked footer."""

        columns = 72
        rows = 12
        duration_seconds = 5.5
        pb1 = log.pb(90).title("PB1").manual()
        pb2 = log.pb(120).title("PB2").manual()
        buffer = real_terminal_stream()
        emitted_messages: list[str] = []

        def assert_screen_layout(raw: str, latest_messages: list[str] | None = None) -> None:
            """Replay the visible terminal and ensure recent logs stay above the footer."""

            screen = replay_terminal_screen(raw, screen_height=rows)
            self.assertGreaterEqual(len(screen), 2)
            self.assertIn("PB1", screen[-2])
            self.assertIn("PB2", screen[-1])
            self.assertNotIn("INFO", screen[-2])
            self.assertNotIn("INFO", screen[-1])
            for line in screen[:-2]:
                self.assertNotIn("PB1", line)
                self.assertNotIn("PB2", line)
            if latest_messages:
                for message in latest_messages:
                    self.assertTrue(
                        any(message in line for line in screen[:-2]),
                        msg=f"expected recent log {message!r} above stacked bars in {screen!r}",
                    )

        try:
            with patch("logbar.progress.terminal_size", return_value=(columns, rows)), \
                 patch("logbar.logbar.terminal_size", return_value=(columns, rows)), \
                 patch("logbar.logbar._should_refresh_in_background", return_value=False), \
                 patch("logbar.logbar._ensure_background_refresh_thread", return_value=None), \
                 redirect_stdout(buffer):
                pb1.draw()
                pb2.draw()
                assert_screen_layout(buffer.getvalue())

                started = time.perf_counter()
                next_log_at = started + 0.5
                log_count = 0

                while True:
                    elapsed = time.perf_counter() - started
                    if elapsed >= duration_seconds:
                        break

                    pb1.current_iter_step = min(len(pb1), pb1.current_iter_step + 1)
                    pb1.draw()
                    pb2.current_iter_step = min(len(pb2), pb2.current_iter_step + 2)
                    pb2.draw()

                    now = time.perf_counter()
                    if now >= next_log_at:
                        log_count += 1
                        latest_message = f"coexist tick {log_count}"
                        emitted_messages.append(latest_message)
                        log.info(latest_message)
                        next_log_at += 0.5

                    assert_screen_layout(buffer.getvalue(), latest_messages=emitted_messages[-4:])
                    sleep(0.08)

            self.assertGreaterEqual(time.perf_counter() - started, duration_seconds)
            self.assertGreaterEqual(log_count, 8)
            assert_screen_layout(buffer.getvalue(), latest_messages=emitted_messages[-4:])
        finally:
            with redirect_stdout(StringIO()):
                pb2.close()
                pb1.close()
