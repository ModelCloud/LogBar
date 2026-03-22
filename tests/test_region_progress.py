# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for pane-local progress bars rendered through split sessions."""

import time
import unittest
from unittest import mock

from logbar.layout import LeafNode, SplitDirection, SplitNode
from logbar.session import RegionScreenSession
from tests._stream_helpers import FakeTTY, MirroredTTY, real_terminal_stream


class TestRegionProgress(unittest.TestCase):
    """Coverage for pane-local progress bars and spinners."""

    def test_split_session_supports_staggered_logs_and_stacked_progress_per_pane(self):
        """Exercise a realistic two-pane session with interleaved logs and mixed progress intervals."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True), \
             mock.patch("logbar.progress.time.time", return_value=100.0):
            session = RegionScreenSession.columns(
                "left",
                "right",
                weights=(1, 1),
                stream=FakeTTY(),
                size_provider=lambda: (80, 8),
                use_alternate_screen=False,
                auto_render=False,
            )

            left_logger = session.create_logger("left", supports_ansi=False)
            right_logger = session.create_logger("right", supports_ansi=False)
            left_logger.setLevel("INFO")
            right_logger.setLevel("INFO")

            left_fast = session.pb(4, region_id="left", output_interval=1).manual().style("mono").title("L1")
            left_slow = session.pb(4, region_id="left", output_interval=2).manual().style("mono").title("L2")
            right_fast = session.pb(6, region_id="right", output_interval=1).manual().style("mono").title("R1")
            right_slow = session.pb(6, region_id="right", output_interval=3).manual().style("mono").title("R2")
            session.render()
            viewports = session.coordinator.resolve_viewports(columns=80, lines=8)
            left_viewport = viewports["left"]
            right_viewport = viewports["right"]

            left_logger.info("left start")
            right_logger.info("right start")
            left_fast.next()
            left_fast.draw()
            right_fast.next()
            right_fast.draw()
            left_slow.next()
            left_slow.draw()
            right_slow.next()
            right_slow.draw()
            right_slow.next()
            right_slow.draw()
            left_logger.info("left mid")
            right_logger.info("right mid")

            mid_rows = session.render()
            mid_left_rows = [
                row[left_viewport.x:left_viewport.x + left_viewport.width].rstrip()
                for row in mid_rows
            ]
            mid_right_rows = [
                row[right_viewport.x:right_viewport.x + right_viewport.width].rstrip()
                for row in mid_rows
            ]

            self.assertEqual(mid_left_rows[4], "INFO  left start")
            self.assertEqual(mid_right_rows[4], "INFO  right start")
            self.assertEqual(mid_left_rows[5], "INFO  left mid")
            self.assertEqual(mid_right_rows[5], "INFO  right mid")
            self.assertIn("L1 [1 of 4]", mid_left_rows[6])
            self.assertIn("[1/4] 25", mid_left_rows[6])
            self.assertIn("R1 [1 of 6]", mid_right_rows[6])
            self.assertIn("[1/6]", mid_right_rows[6])
            self.assertIn("L2 [0 of 4]", mid_left_rows[7])
            self.assertIn("[0/4] 0.", mid_left_rows[7])
            self.assertIn("R2 [0 of 6]", mid_right_rows[7])
            self.assertIn("[0/6]", mid_right_rows[7])

            left_fast.next()
            left_fast.draw()
            left_slow.next()
            left_slow.draw()
            right_fast.next()
            right_fast.draw()
            right_slow.next()
            right_slow.draw()
            left_logger.info("left end")
            right_logger.info("right end")

            final_rows = session.render()
            final_left_rows = [
                row[left_viewport.x:left_viewport.x + left_viewport.width].rstrip()
                for row in final_rows
            ]
            final_right_rows = [
                row[right_viewport.x:right_viewport.x + right_viewport.width].rstrip()
                for row in final_rows
            ]

            self.assertEqual(final_left_rows[3], "INFO  left start")
            self.assertEqual(final_right_rows[3], "INFO  right start")
            self.assertEqual(final_left_rows[4], "INFO  left mid")
            self.assertEqual(final_right_rows[4], "INFO  right mid")
            self.assertEqual(final_left_rows[5], "INFO  left end")
            self.assertEqual(final_right_rows[5], "INFO  right end")
            self.assertIn("L1 [2 of 4]", final_left_rows[6])
            self.assertIn("[2/4] 50", final_left_rows[6])
            self.assertIn("R1 [2 of 6]", final_right_rows[6])
            self.assertIn("[2/6]", final_right_rows[6])
            self.assertIn("L2 [2 of 4]", final_left_rows[7])
            self.assertIn("[2/4] 50", final_left_rows[7])
            self.assertIn("R2 [3 of 6]", final_right_rows[7])
            self.assertIn("[3/6]", final_right_rows[7])

            left_fast.close()
            left_slow.close()
            right_fast.close()
            right_slow.close()
            session.close()

    def test_split_session_real_time_progress_and_logs_run_for_fifteen_seconds(self):
        """Run one human-followable split session for 15 seconds with staggered pane activity."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True):
            stream = real_terminal_stream()
            session = RegionScreenSession.columns(
                "left",
                "right",
                weights=(1, 1),
                stream=stream,
                use_alternate_screen=isinstance(stream, MirroredTTY),
                auto_render=True,
            )

            left_logger = session.create_logger("left", supports_ansi=False)
            right_logger = session.create_logger("right", supports_ansi=False)
            left_logger.setLevel("INFO")
            right_logger.setLevel("INFO")

            left_fast = session.pb(5, region_id="left", output_interval=1).manual().style("mono").title("L-fast")
            left_slow = session.pb(4, region_id="left", output_interval=2).manual().style("mono").title("L-slow")
            right_fast = session.pb(5, region_id="right", output_interval=1).manual().style("mono").title("R-fast")
            right_slow = session.pb(6, region_id="right", output_interval=3).manual().style("mono").title("R-slow")

            def advance(pb, steps: int = 1) -> None:
                """Advance one pane-local bar by the requested number of logical steps."""

                for _ in range(steps):
                    pb.next()
                pb.draw()

            schedule = [
                (0.5, lambda: left_logger.info("left start")),
                (1.0, lambda: advance(left_fast)),
                (1.5, lambda: right_logger.info("right start")),
                (1.75, lambda: advance(right_fast)),
                (2.0, lambda: advance(right_slow)),
                (2.5, lambda: advance(left_slow)),
                (3.5, lambda: advance(left_fast)),
                (4.0, lambda: advance(right_fast)),
                (4.5, lambda: advance(right_slow)),
                (5.0, lambda: advance(left_slow)),
                (5.5, lambda: advance(left_fast)),
                (7.0, lambda: advance(right_slow)),
                (7.5, lambda: advance(right_fast)),
                (8.0, lambda: left_logger.info("left mid")),
                (8.5, lambda: advance(left_slow)),
                (10.0, lambda: advance(left_fast)),
                (10.5, lambda: advance(right_slow)),
                (11.0, lambda: advance(right_fast)),
                (12.0, lambda: left_logger.info("left end")),
                (12.5, lambda: advance(right_slow)),
                (13.5, lambda: advance(left_fast)),
                (14.0, lambda: right_logger.info("right end")),
                (14.5, lambda: advance(left_slow)),
                (15.0, lambda: advance(right_fast)),
                (15.0, lambda: advance(right_slow)),
            ]

            try:
                # Flush the initial zero-state footer so later renders honor the
                # configured output intervals instead of the initial dirty state.
                session.render()

                start = time.monotonic()
                for offset_seconds, action in schedule:
                    remaining = (start + offset_seconds) - time.monotonic()
                    if remaining > 0:
                        time.sleep(remaining)
                    action()

                elapsed = time.monotonic() - start
                state = session.screen.backend_state()
                viewports = session.coordinator.resolve_viewports(
                    columns=state.columns,
                    lines=state.lines,
                )
                left_viewport = viewports["left"]
                right_viewport = viewports["right"]
                final_rows = session.render(backend_state=state)
                left_rows = [
                    row[left_viewport.x:left_viewport.x + left_viewport.width].rstrip()
                    for row in final_rows
                ]
                right_rows = [
                    row[right_viewport.x:right_viewport.x + right_viewport.width].rstrip()
                    for row in final_rows
                ]

                self.assertGreaterEqual(elapsed, 15.0)
                self.assertIn("INFO  left start", left_rows)
                self.assertIn("INFO  left mid", left_rows)
                self.assertIn("INFO  left end", left_rows)
                self.assertIn("INFO  right start", right_rows)
                self.assertIn("INFO  right end", right_rows)
                self.assertIn("L-fast [5 of 5]", left_rows[-2])
                self.assertIn("[5/", left_rows[-2])
                self.assertIn("L-slow [4 of 4]", left_rows[-1])
                self.assertIn("[4/", left_rows[-1])
                self.assertIn("R-fast [5 of 5]", right_rows[-2])
                self.assertIn("[5/", right_rows[-2])
                self.assertIn("R-slow [6 of 6]", right_rows[-1])
                self.assertIn("[6/", right_rows[-1])
                self.assertIn("left start", stream.getvalue())
                self.assertIn("right end", stream.getvalue())
            finally:
                left_fast.close()
                left_slow.close()
                right_fast.close()
                right_slow.close()
                session.close()

    def test_session_progress_footer_coexists_with_static_footer_lines(self):
        """Pane progress rows should append beneath static footer lines."""

        with mock.patch.dict("logbar.terminal.os.environ", {"NO_COLOR": "1"}, clear=True), \
             mock.patch("logbar.progress.time.time", return_value=100.0):
            stream = FakeTTY()
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
                stream=FakeTTY(),
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
