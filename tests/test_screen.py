# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for the experimental region-composed ANSI screen backend."""

import io
import unittest

from logbar.coordinator import RenderCoordinator
from logbar.layout import LeafNode, SplitDirection, SplitNode
from logbar.screen import RegionScreen
from logbar.terminal import RenderBackendState


class _FakeTTY(io.StringIO):
    """String buffer that reports TTY support for ANSI render tests."""

    def isatty(self):
        """Pretend to be a cursor-capable terminal."""

        return True


class _FakePipe(io.StringIO):
    """String buffer that behaves like a plain redirected stream."""

    def isatty(self):
        """Report non-interactive stream mode."""

        return False


class _RecordingBackend:
    """Small fake backend used to prove RegionScreen delegates backend I/O."""

    def __init__(self):
        """Capture all render calls for assertions."""

        self.calls = []
        self.closed = False
        self._state = RenderBackendState(
            columns=12,
            lines=2,
            is_tty=False,
            notebook=False,
            supports_cursor=False,
            supports_ansi=False,
            supports_styling=False,
        )

    def backend_state(self):
        """Return one stable backend snapshot."""

        return self._state

    def render_lines(self, lines, *, backend_state=None):
        """Record the composed frame that RegionScreen asked to paint."""

        self.calls.append((list(lines), backend_state))

    def close(self):
        """Record backend shutdown."""

        self.closed = True


class TestRegionScreen(unittest.TestCase):
    """Coverage for the explicit region-composed terminal backend."""

    def test_region_screen_can_delegate_to_a_custom_backend(self):
        """RegionScreen should compose rows itself and delegate I/O to its backend."""

        coordinator = RenderCoordinator()
        logger = coordinator.create_region_logger(coordinator.root_region_id, supports_ansi=False)
        logger.setLevel("INFO")
        logger.info("hello")

        backend = _RecordingBackend()
        screen = RegionScreen(coordinator, backend=backend)

        rows = screen.render()

        self.assertEqual(rows, ["            ", "INFO  hello "])
        self.assertEqual(backend.calls, [
            (["            ", "INFO  hello "], backend.backend_state()),
        ])

        screen.close()

        self.assertTrue(backend.closed)

    def test_region_screen_first_render_enters_alt_screen_and_paints_full_frame(self):
        """First render should enter alt-screen mode and draw every row."""

        coordinator = RenderCoordinator()
        coordinator.set_layout(
            SplitNode(
                direction=SplitDirection.LEFT_RIGHT,
                children=(LeafNode("left"), LeafNode("right")),
            )
        )
        left_logger = coordinator.create_region_logger("left", supports_ansi=False)
        right_logger = coordinator.create_region_logger("right", supports_ansi=False)
        left_logger.setLevel("INFO")
        right_logger.setLevel("INFO")
        left_logger.info("a1")
        right_logger.warn("b1")

        stream = _FakeTTY()
        screen = RegionScreen(
            coordinator,
            stream=stream,
            size_provider=lambda: (20, 4),
        )

        rows = screen.render()

        self.assertEqual(rows, [
            "          |         ",
            "          |         ",
            "          |         ",
            "INFO  a1  |WARN  b1 ",
        ])
        output = stream.getvalue()
        self.assertTrue(output.startswith("\033[?1049h\033[?25l\033[2J"))
        self.assertEqual(output.count("\033[2K"), 4)
        self.assertIn("\033[4;1H\033[2KINFO  a1  |WARN  b1 ", output)

        screen.close()

    def test_region_screen_second_render_only_rewrites_changed_rows(self):
        """Stable-size rerenders should touch only rows whose content changed."""

        coordinator = RenderCoordinator()
        coordinator.set_layout(
            SplitNode(
                direction=SplitDirection.LEFT_RIGHT,
                children=(LeafNode("left"), LeafNode("right")),
            )
        )
        left_logger = coordinator.create_region_logger("left", supports_ansi=False)
        right_logger = coordinator.create_region_logger("right", supports_ansi=False)
        left_logger.setLevel("INFO")
        right_logger.setLevel("INFO")
        left_logger.info("a1")
        right_logger.warn("b1")

        stream = _FakeTTY()
        screen = RegionScreen(
            coordinator,
            stream=stream,
            size_provider=lambda: (20, 4),
            use_alternate_screen=False,
        )

        screen.render()
        stream.seek(0)
        stream.truncate(0)

        left_logger.info("a2")
        rows = screen.render()

        self.assertEqual(rows, [
            "          |         ",
            "          |         ",
            "INFO  a1  |         ",
            "INFO  a2  |WARN  b1 ",
        ])
        output = stream.getvalue()
        self.assertNotIn("\033[2J", output)
        self.assertEqual(output.count("\033[2K"), 2)
        self.assertIn("\033[3;1H\033[2KINFO  a1  |         ", output)
        self.assertIn("\033[4;1H\033[2KINFO  a2  |WARN  b1 ", output)
        self.assertTrue(output.endswith("\033[1;1H"))

        screen.close()

    def test_region_screen_close_restores_cursor_and_alt_screen(self):
        """Closing the screen should restore terminal state."""

        coordinator = RenderCoordinator()
        logger = coordinator.create_region_logger(coordinator.root_region_id, supports_ansi=False)
        logger.setLevel("INFO")
        logger.info("hello")

        stream = _FakeTTY()
        screen = RegionScreen(
            coordinator,
            stream=stream,
            size_provider=lambda: (20, 1),
        )

        screen.render()
        stream.seek(0)
        stream.truncate(0)

        screen.close()

        self.assertEqual(stream.getvalue(), "\033[?25h\033[?1049l")

    def test_region_screen_plain_stream_fallback_strips_ansi_and_linearizes_rows(self):
        """Non-cursor streams should receive plain newline-separated frame rows."""

        coordinator = RenderCoordinator()
        logger = coordinator.create_region_logger(coordinator.root_region_id, supports_ansi=True)
        logger.setLevel("INFO")
        logger.info("hello")

        stream = _FakePipe()
        screen = RegionScreen(
            coordinator,
            stream=stream,
            size_provider=lambda: (20, 1),
        )

        rows = screen.render()

        self.assertEqual(rows, ["INFO  hello         "])
        self.assertEqual(stream.getvalue(), "INFO  hello         \n")
        self.assertNotIn("\033[", stream.getvalue())
