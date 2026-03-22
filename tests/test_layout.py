# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for ncurses-like region layout primitives."""

import unittest

from logbar.layout import DividerAssignment, LeafNode, SplitDirection, SplitNode, Viewport, columns, pane, resolve_dividers, resolve_layout, rows


class TestLayout(unittest.TestCase):
    """Coverage for nested split tree viewport resolution."""

    def test_nested_split_resolves_left_right_then_top_bottom(self):
        """Resolve a split tree into the expected leaf rectangles."""

        layout = SplitNode(
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

        resolved = resolve_layout(layout, Viewport(0, 0, 50, 15))

        self.assertEqual(resolved["left"], Viewport(0, 0, 20, 15))
        self.assertEqual(resolved["right_top"], Viewport(21, 0, 29, 5))
        self.assertEqual(resolved["right_bottom"], Viewport(21, 6, 29, 9))

    def test_layout_distributes_remainder_to_earliest_children(self):
        """Keep fractional split allocation deterministic for odd dimensions."""

        layout = SplitNode(
            direction=SplitDirection.LEFT_RIGHT,
            weights=(1, 1, 1),
            children=(
                LeafNode("one"),
                LeafNode("two"),
                LeafNode("three"),
            ),
        )

        resolved = resolve_layout(layout, Viewport(0, 0, 8, 4))

        self.assertEqual(resolved["one"], Viewport(0, 0, 2, 4))
        self.assertEqual(resolved["two"], Viewport(3, 0, 2, 4))
        self.assertEqual(resolved["three"], Viewport(6, 0, 2, 4))

    def test_layout_respects_gutters_between_children(self):
        """Subtract gutter cells from the available split area."""

        layout = SplitNode(
            direction=SplitDirection.TOP_BOTTOM,
            gutter=1,
            children=(
                LeafNode("top"),
                LeafNode("bottom"),
            ),
        )

        resolved = resolve_layout(layout, Viewport(2, 3, 10, 7))

        self.assertEqual(resolved["top"], Viewport(2, 3, 10, 3))
        self.assertEqual(resolved["bottom"], Viewport(2, 7, 10, 3))

    def test_duplicate_region_ids_raise(self):
        """Reject ambiguous layouts that resolve one region name twice."""

        layout = SplitNode(
            direction=SplitDirection.LEFT_RIGHT,
            children=(
                LeafNode("dup"),
                LeafNode("dup"),
            ),
        )

        with self.assertRaises(ValueError):
            resolve_layout(layout, Viewport(0, 0, 10, 2))

    def test_public_layout_helpers_build_nested_split_trees(self):
        """Public helpers should coerce strings into the expected nested layout tree."""

        layout = columns(
            "left",
            rows("right_top", pane("right_bottom")),
            weights=(2, 3),
        )

        resolved = resolve_layout(layout, Viewport(0, 0, 50, 15))

        self.assertEqual(resolved["left"], Viewport(0, 0, 20, 15))
        self.assertEqual(resolved["right_top"], Viewport(21, 0, 29, 7))
        self.assertEqual(resolved["right_bottom"], Viewport(21, 8, 29, 7))

    def test_default_split_layout_resolves_one_char_dividers(self):
        """Default split nodes should reserve and expose a one-cell divider."""

        layout = columns("left", rows("right_top", "right_bottom"))

        dividers = resolve_dividers(layout, Viewport(0, 0, 20, 8))

        self.assertEqual(dividers, [
            DividerAssignment(viewport=Viewport(10, 0, 1, 8), fill="|"),
            DividerAssignment(viewport=Viewport(11, 4, 9, 1), fill="-"),
        ])

    def test_public_layout_helpers_reject_unknown_child_types(self):
        """Public helpers should fail fast on unsupported child values."""

        with self.assertRaises(TypeError):
            columns("left", 7)  # type: ignore[arg-type]
