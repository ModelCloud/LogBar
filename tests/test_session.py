# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for high-level split-pane region screen sessions."""

import io
import unittest

from logbar.layout import LeafNode, SplitDirection, SplitNode
from logbar.session import RegionScreenSession


class _FakeTTY(io.StringIO):
    """String buffer that reports TTY support for ANSI render tests."""

    def isatty(self):
        """Pretend to be a cursor-capable terminal."""

        return True


class TestRegionScreenSession(unittest.TestCase):
    """Coverage for auto-render split-pane session behavior."""

    def test_session_auto_renders_after_log_and_footer_mutations(self):
        """Auto-render sessions should repaint after logger state changes."""

        stream = _FakeTTY()
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
        left_logger = session.create_logger("left")
        right_logger = session.create_logger("right")
        left_logger.setLevel("INFO")
        right_logger.setLevel("INFO")

        left_logger.info("a1")

        self.assertIn("\033[2J", stream.getvalue())
        self.assertIn("\033[4;1H\033[2KINFO  a1            ", stream.getvalue())

        stream.seek(0)
        stream.truncate(0)

        right_logger.set_footer_lines(["rb1"])

        self.assertEqual(stream.getvalue().count("\033[2K"), 1)
        self.assertIn("\033[4;1H\033[2KINFO  a1  rb1       ", stream.getvalue())

        session.close()

    def test_session_manual_render_mode_defers_output_until_render_called(self):
        """Manual sessions should not repaint until explicitly asked."""

        stream = _FakeTTY()
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

        stream = _FakeTTY()
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
