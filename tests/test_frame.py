# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for cell-based frame composition primitives."""

import unittest

from logbar.frame import Cell, CellBuffer
from logbar.layout import Viewport


class TestFrame(unittest.TestCase):
    """Coverage for local cell surfaces and composition helpers."""

    def test_draw_text_clips_to_buffer_bounds(self):
        """Ignore text beyond the visible row width."""

        buffer = CellBuffer(5, 2)
        buffer.draw_text(3, 0, "abcdef")

        self.assertEqual(buffer.to_plain_lines(), ["   ab", "     "])

    def test_fill_viewport_clips_to_surface(self):
        """Fill only the overlap between a viewport and the buffer."""

        buffer = CellBuffer(4, 3)
        buffer.fill_viewport(Viewport(2, 1, 4, 3), cell=Cell("#"))

        self.assertEqual(buffer.to_plain_lines(), [
            "    ",
            "  ##",
            "  ##",
        ])

    def test_blit_copies_cells_using_destination_offset(self):
        """Compose a child buffer into a parent surface at one offset."""

        parent = CellBuffer(6, 4)
        child = CellBuffer(3, 2)
        child.draw_text(0, 0, "abc")
        child.draw_text(0, 1, "xyz")

        parent.blit(child, dest_x=2, dest_y=1)

        self.assertEqual(parent.to_plain_lines(), [
            "      ",
            "  abc ",
            "  xyz ",
            "      ",
        ])

    def test_blit_honors_source_viewport(self):
        """Allow callers to copy only a clipped slice of a child surface."""

        parent = CellBuffer(4, 2)
        child = CellBuffer(4, 2)
        child.draw_text(0, 0, "abcd")
        child.draw_text(0, 1, "wxyz")

        parent.blit(child, dest_x=1, dest_y=0, source_viewport=Viewport(1, 0, 2, 2))

        self.assertEqual(parent.to_plain_lines(), [
            " bc ",
            " xy ",
        ])
