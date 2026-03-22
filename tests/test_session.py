# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for high-level split-pane region screen sessions."""

import time
import unittest
from unittest import mock

from logbar.layout import LeafNode, SplitDirection, SplitNode, rows
from logbar.session import RegionScreenSession
from tests._stream_helpers import FakeTTY


class TestRegionScreenSession(unittest.TestCase):
    """Coverage for auto-render split-pane session behavior."""

    def test_session_auto_renders_after_log_and_footer_mutations(self):
        """Auto-render sessions should repaint after logger state changes."""

        stream = FakeTTY()
        session = RegionScreenSession(
            layout_root=SplitNode(
                direction=SplitDirection.LEFT_RIGHT,
                children=(LeafNode("left"), LeafNode("right")),
            ),
            stream=stream,
            size_provider=lambda: (20, 4),
            use_alternate_screen=False,
            auto_render=True,
        )
        left_logger = session.create_logger("left", supports_ansi=False)
        right_logger = session.create_logger("right", supports_ansi=False)
        left_logger.setLevel("INFO")
        right_logger.setLevel("INFO")

        left_logger.info("a1")

        self.assertIn("\033[2J", stream.getvalue())
        self.assertIn("\033[4;1H\033[2KINFO  a1  |         ", stream.getvalue())

        stream.seek(0)
        stream.truncate(0)

        right_logger.set_footer_lines(["rb1"])

        self.assertEqual(stream.getvalue().count("\033[2K"), 1)
        self.assertIn("\033[4;1H\033[2KINFO  a1  |rb1      ", stream.getvalue())

        session.close()

    def test_session_manual_render_mode_defers_output_until_render_called(self):
        """Manual sessions should not repaint until explicitly asked."""

        stream = FakeTTY()
        session = RegionScreenSession(
            stream=stream,
            size_provider=lambda: (20, 2),
            use_alternate_screen=False,
            auto_render=False,
        )
        logger = session.create_logger(session.coordinator.root_region_id, supports_ansi=False)
        logger.setLevel("INFO")

        logger.info("hello")
        logger.set_footer_lines(["footer"])

        self.assertEqual(stream.getvalue(), "")

        rows = session.render()

        self.assertEqual(rows, [
            "INFO  hello         ",
            "footer              ",
        ])
        self.assertIn("\033[2J", stream.getvalue())
        self.assertIn("\033[1;1H\033[2KINFO  hello         ", stream.getvalue())
        self.assertIn("\033[2;1H\033[2Kfooter              ", stream.getvalue())

        session.close()

    def test_session_context_manager_restores_terminal_state(self):
        """Leaving the session scope should restore cursor and alt-screen state."""

        stream = FakeTTY()
        with RegionScreenSession(
            stream=stream,
            size_provider=lambda: (20, 1),
            use_alternate_screen=True,
            auto_render=True,
        ) as session:
            logger = session.create_logger(session.coordinator.root_region_id, supports_ansi=False)
            logger.setLevel("INFO")
            logger.info("hello")

        self.assertTrue(stream.getvalue().startswith("\033[?1049h\033[?25l"))
        self.assertTrue(stream.getvalue().endswith("\033[?25h\033[?1049l"))

    def test_session_auto_refresh_thread_updates_spinner_and_stops_after_detach(self):
        """Auto-render sessions should background-refresh pane-local spinners."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True), \
             mock.patch("logbar.progress.time.time", return_value=100.0):
            stream = FakeTTY()
            session = RegionScreenSession(
                stream=stream,
                size_provider=lambda: (80, 2),
                use_alternate_screen=False,
                auto_render=True,
                background_refresh=True,
                refresh_interval_seconds=0.01,
            )

            spinner = session.spinner(title="spin", interval=0.01, tail_length=2)
            spinner.style("mono")

            thread = session._refresh_thread
            self.assertIsNotNone(thread)
            self.assertTrue(thread.is_alive())

            initial_len = len(stream.getvalue())
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline and len(stream.getvalue()) <= initial_len:
                time.sleep(0.01)

            self.assertGreater(len(stream.getvalue()), initial_len)

            spinner.close()

            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                thread = session._refresh_thread
                if thread is None or not thread.is_alive():
                    break
                time.sleep(0.01)

            thread = session._refresh_thread
            self.assertTrue(thread is None or not thread.is_alive())

            session.close()

    def test_session_manual_mode_does_not_start_background_refresh_thread(self):
        """Manual sessions should keep pane progress refresh under caller control."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True), \
             mock.patch("logbar.progress.time.time", return_value=100.0):
            session = RegionScreenSession(
                stream=FakeTTY(),
                size_provider=lambda: (80, 2),
                use_alternate_screen=False,
                auto_render=False,
                background_refresh=True,
                refresh_interval_seconds=0.01,
            )

            spinner = session.spinner(title="spin", interval=0.01, tail_length=2)

            self.assertFalse(session.background_refresh_enabled)
            self.assertIsNone(session._refresh_thread)

            spinner.close()
            session.close()

    def test_session_columns_helper_builds_nested_public_layouts(self):
        """Public session helpers should create split sessions without raw layout nodes."""

        stream = FakeTTY()
        session = RegionScreenSession.columns(
            "left",
            rows("right_top", "right_bottom"),
            weights=(2, 3),
            stream=stream,
            size_provider=lambda: (30, 4),
            use_alternate_screen=False,
            auto_render=False,
        )

        left_logger = session.create_logger("left", supports_ansi=False)
        right_bottom_logger = session.create_logger("right_bottom", supports_ansi=False)
        left_logger.setLevel("INFO")
        right_bottom_logger.setLevel("INFO")
        left_logger.info("L")
        right_bottom_logger.info("RB")

        rows_out = session.render()

        self.assertEqual(rows_out, [
            "            |                 ",
            "            |                 ",
            "            |-----------------",
            "INFO  L     |INFO  RB         ",
        ])

        session.close()
