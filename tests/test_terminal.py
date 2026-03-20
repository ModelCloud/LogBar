# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import os
import unittest
from unittest import mock

from logbar import terminal as terminal_module


class TestTerminal(unittest.TestCase):
    def test_terminal_size_prefers_stream_terminal_query(self):
        class StreamWithFileno:
            def fileno(self):
                return 17

        stream = StreamWithFileno()

        with mock.patch.dict("logbar.terminal.os.environ", {}, clear=True), \
             mock.patch("logbar.terminal.os.get_terminal_size", return_value=os.terminal_size((123, 45))), \
             mock.patch("logbar.terminal.shutil.get_terminal_size", side_effect=AssertionError("should not use shutil fallback")):
            columns, lines = terminal_module.terminal_size(stream=stream)

        self.assertEqual((columns, lines), (123, 45))

    def test_render_backend_state_honors_cursor_policy(self):
        class FakeStream:
            def __init__(self, is_tty: bool):
                self._is_tty = is_tty

            def isatty(self):
                return self._is_tty

        size_provider = lambda: (90, 33)

        with mock.patch.dict("logbar.terminal.os.environ", {"LOGBAR_FORCE_TERMINAL_CURSOR": "1"}, clear=True):
            forced = terminal_module.render_backend_state(
                stream=FakeStream(False),
                size_provider=size_provider,
            )

        with mock.patch.dict("logbar.terminal.os.environ", {}, clear=True):
            notebook = terminal_module.render_backend_state(
                stream=FakeStream(True),
                size_provider=size_provider,
                notebook=True,
            )

        self.assertEqual((forced.columns, forced.lines), (90, 33))
        self.assertFalse(forced.is_tty)
        self.assertTrue(forced.supports_cursor)
        self.assertFalse(forced.supports_ansi)
        self.assertFalse(forced.supports_styling)
        self.assertTrue(notebook.is_tty)
        self.assertTrue(notebook.notebook)
        self.assertFalse(notebook.supports_cursor)
        self.assertFalse(notebook.supports_ansi)
        self.assertTrue(notebook.supports_styling)

    def test_render_backend_state_tracks_ansi_policy_separately(self):
        class FakeStream:
            def __init__(self, is_tty: bool):
                self._is_tty = is_tty

            def isatty(self):
                return self._is_tty

        size_provider = lambda: (72, 20)

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True):
            no_color = terminal_module.render_backend_state(
                stream=FakeStream(True),
                size_provider=size_provider,
            )

        with mock.patch.dict("logbar.terminal.os.environ", {"FORCE_COLOR": "1"}, clear=True):
            forced_color = terminal_module.render_backend_state(
                stream=FakeStream(False),
                size_provider=size_provider,
            )

        self.assertFalse(no_color.supports_ansi)
        self.assertFalse(no_color.supports_styling)
        self.assertTrue(no_color.supports_cursor)
        self.assertTrue(forced_color.supports_ansi)
        self.assertTrue(forced_color.supports_styling)
        self.assertFalse(forced_color.supports_cursor)
