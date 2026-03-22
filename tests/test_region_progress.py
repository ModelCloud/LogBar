# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for pane-local progress bars rendered through split sessions."""

import io
import unittest
from unittest import mock

from logbar.layout import LeafNode, SplitDirection, SplitNode
from logbar.session import RegionScreenSession


class _FakeTTY(io.StringIO):
    """String buffer that reports TTY support for ANSI render tests."""

    def isatty(self):
        """Pretend to be a cursor-capable terminal."""

        return True


class TestRegionProgress(unittest.TestCase):
    """Coverage for pane-local progress bars and spinners."""

    def test_session_progress_footer_coexists_with_static_footer_lines(self):
        """Pane progress rows should append beneath static footer lines."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True), \
             mock.patch("logbar.progress.time.time", return_value=100.0):
            stream = _FakeTTY()
            session = RegionScreenSession(
                stream=stream,
                size_provider=lambda: (80, 4),
                use_alternate_screen=False,
                auto_render=False,
            )
            logger = session.create_logger(session.coordinator.root_region_id, supports_ansi=False)
            logger.setLevel("INFO")
            logger.info("hello")
            logger.set_footer_lines(["static"])

            pb = session.pb(4, output_interval=1)
            pb.style("mono").title("job")
            pb.next()
            pb.draw(force=True)

            rows = session.render()

            self.assertTrue(rows[-2].startswith("static"))
            self.assertTrue(rows[-1].startswith("job [1 of 4] "))
            self.assertIn("25.0%", rows[-1])

            pb.close()
            rows = session.render()

            self.assertTrue(rows[-1].startswith("static"))
            self.assertNotIn("25.0%", rows[-1])
            self.assertTrue(any("hello" in row for row in rows))

            session.close()

    def test_session_spinner_pulse_updates_one_pane_without_affecting_sibling_logs(self):
        """Spinner frames should update in their pane footer while sibling logs remain stable."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True), \
             mock.patch("logbar.progress.time.time", return_value=100.0):
            session = RegionScreenSession(
                layout_root=SplitNode(
                    direction=SplitDirection.LEFT_RIGHT,
                    children=(LeafNode("left"), LeafNode("right")),
                ),
                stream=_FakeTTY(),
                size_provider=lambda: (120, 4),
                use_alternate_screen=False,
                auto_render=False,
            )
            left_spinner = session.spinner(region_id="left", title="spin", interval=0.5, tail_length=2)
            left_spinner.style("mono")

            right_logger = session.create_logger("right", supports_ansi=False)
            right_logger.setLevel("INFO")
            right_logger.info("worker ready")

            before = session.render()
            left_spinner.pulse()
            after = session.render()

            self.assertIn("worker ready", before[-1])
            self.assertIn("worker ready", after[-1])
            self.assertIn("spin", before[-1])
            self.assertIn("spin", after[-1])
            self.assertNotEqual(before[-1][:60], after[-1][:60])

            left_spinner.close()
            session.close()
