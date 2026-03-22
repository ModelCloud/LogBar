# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for the region-aware render coordinator."""

import unittest

from logbar.coordinator import DEFAULT_ROOT_REGION_ID, RenderCoordinator
from logbar.layout import LeafNode, SplitDirection, SplitNode, Viewport


class TestRenderCoordinator(unittest.TestCase):
    """Coverage for layout-aware coordinator behavior."""

    def test_default_layout_resolves_one_root_region(self):
        """New coordinators should start in single-pane mode."""

        coordinator = RenderCoordinator()

        resolved = coordinator.resolve_viewports(columns=12, lines=4)

        self.assertEqual(coordinator.root_region_id, DEFAULT_ROOT_REGION_ID)
        self.assertEqual(resolved, {
            DEFAULT_ROOT_REGION_ID: Viewport(0, 0, 12, 4),
        })

    def test_set_layout_supports_nested_split_trees(self):
        """The coordinator should resolve nested region layouts deterministically."""

        coordinator = RenderCoordinator()
        coordinator.set_layout(
            SplitNode(
                direction=SplitDirection.LEFT_RIGHT,
                weights=(2, 3),
                children=(
                    LeafNode("left"),
                    SplitNode(
                        direction=SplitDirection.TOP_BOTTOM,
                        weights=(1, 2),
                        children=(
                            LeafNode("right_top"),
                            LeafNode("right_bottom"),
                        ),
                    ),
                ),
            )
        )

        resolved = coordinator.resolve_viewports(viewport=Viewport(0, 0, 50, 15))

        self.assertEqual(resolved["left"], Viewport(0, 0, 20, 15))
        self.assertEqual(resolved["right_top"], Viewport(20, 0, 30, 5))
        self.assertEqual(resolved["right_bottom"], Viewport(20, 5, 30, 10))

    def test_resolve_registered_regions_binds_objects_in_leaf_order(self):
        """Leaf resolution should preserve layout order for future compositors."""

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

        left_region = object()
        right_region = object()
        coordinator.register_region("left", left_region)
        coordinator.register_region("right", right_region)

        resolved = coordinator.resolve_registered_regions(columns=10, lines=3)

        self.assertEqual(
            [(entry.region_id, entry.region, entry.viewport) for entry in resolved],
            [
                ("left", left_region, Viewport(0, 0, 5, 3)),
                ("right", right_region, Viewport(5, 0, 5, 3)),
            ],
        )

    def test_resolve_registered_regions_rejects_missing_region_objects(self):
        """Layouts should not silently resolve to missing future region instances."""

        coordinator = RenderCoordinator()
        coordinator.set_layout(
            SplitNode(
                direction=SplitDirection.TOP_BOTTOM,
                children=(
                    LeafNode("top"),
                    LeafNode("bottom"),
                ),
            )
        )
        coordinator.register_region("top", object())

        with self.assertRaises(KeyError):
            coordinator.resolve_registered_regions(columns=8, lines=6)

    def test_set_layout_none_restores_single_root_layout(self):
        """Callers should be able to return to the default one-region tree."""

        coordinator = RenderCoordinator(root_region_id="main")
        coordinator.set_layout(
            SplitNode(
                direction=SplitDirection.LEFT_RIGHT,
                children=(LeafNode("left"), LeafNode("right")),
            )
        )

        coordinator.set_layout(None)
        resolved = coordinator.resolve_viewports(columns=7, lines=2)

        self.assertEqual(resolved, {"main": Viewport(0, 0, 7, 2)})
