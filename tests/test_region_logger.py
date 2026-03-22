# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for experimental region-bound logger helpers."""

import unittest

from logbar.coordinator import RenderCoordinator
from logbar.layout import LeafNode, SplitDirection, SplitNode
from logbar.region import LogRegion
from logbar.region_logger import RegionLogBar


class TestRegionLogBar(unittest.TestCase):
    """Coverage for loggers that emit into LogRegion panes."""

    def test_region_logger_appends_formatted_body_lines(self):
        """Region loggers should reuse LogBar message and level formatting."""

        region = LogRegion()
        logger = RegionLogBar("pane", region=region, supports_ansi=False)
        logger.setLevel("INFO")

        logger.info("hello %s", "world")

        self.assertEqual(region.body_lines, ["INFO  hello world"])

    def test_region_logger_preserves_once_helpers_and_footer_mutation(self):
        """The legacy once helpers and explicit footer API should still work."""

        region = LogRegion()
        logger = RegionLogBar("pane", region=region, supports_ansi=False)
        logger.setLevel("INFO")

        logger.warn.once("only once")
        logger.warn.once("only once")
        logger.set_footer_lines(["footer-1"]).append_footer_line("footer-2")

        self.assertEqual(region.body_lines, ["WARN  only once"])
        self.assertEqual(region.footer_lines, ["footer-1", "footer-2"])

    def test_coordinator_region_loggers_compose_split_layouts(self):
        """Coordinator-created region loggers should render through split panes."""

        coordinator = RenderCoordinator()
        coordinator.set_layout(
            SplitNode(
                direction=SplitDirection.LEFT_RIGHT,
                children=(
                    LeafNode("left"),
                    LeafNode("right"),
                ),
            )
        )

        left_logger = coordinator.create_region_logger("left", supports_ansi=False)
        right_logger = coordinator.create_region_logger("right", supports_ansi=False)
        left_logger.setLevel("INFO")
        right_logger.setLevel("INFO")

        left_logger.info("a1")
        left_logger.info("a2")
        left_logger.set_footer_lines(["left-foot"])
        right_logger.warn("b1")
        right_logger.set_footer_lines(["rb1", "rb2"])

        rows = coordinator.compose_layout_lines(columns=20, lines=4)

        self.assertEqual(rows, [
            "          |         ",
            "INFO  a1  |WARN  b1 ",
            "INFO  a2  |rb1      ",
            "left-foot |rb2      ",
        ])
