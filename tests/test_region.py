# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for region render primitives and composed coordinator frames."""

import unittest

from logbar.coordinator import RenderCoordinator
from logbar.layout import LeafNode, SplitDirection, SplitNode, Viewport
from logbar.region import RenderContext, TextRegion


class TestRegion(unittest.TestCase):
    """Coverage for viewport-local region rendering."""

    def test_text_region_renders_from_top_by_default(self):
        """Text regions should render visible lines from the top edge."""

        region = TextRegion(["alpha", "beta", "gamma"])
        buffer = region.render(RenderContext(viewport=Viewport(0, 0, 4, 2), root_viewport=Viewport(0, 0, 4, 2)))

        self.assertEqual(buffer.to_plain_lines(), [
            "alph",
            "beta",
        ])

    def test_text_region_can_anchor_lines_to_bottom(self):
        """Bottom-anchored regions should reserve space above short content."""

        region = TextRegion(["tail"], vertical_anchor="bottom")
        buffer = region.render(RenderContext(viewport=Viewport(0, 0, 4, 3), root_viewport=Viewport(0, 0, 4, 3)))

        self.assertEqual(buffer.to_plain_lines(), [
            "    ",
            "    ",
            "tail",
        ])

    def test_coordinator_composes_registered_regions_into_one_frame(self):
        """Coordinator composition should blit leaf region buffers into root space."""

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
        coordinator.register_region("left", TextRegion(["left", "body"]))
        coordinator.register_region("right", TextRegion(["tail"], vertical_anchor="bottom"))

        frame = coordinator.compose_frame(columns=8, lines=3)

        self.assertEqual(frame.to_plain_lines(), [
            "left    ",
            "body    ",
            "    tail",
        ])
