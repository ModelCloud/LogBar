# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import unittest

from logbar.drawing import CellBarRenderer, strip_ansi, truncate_ansi, visible_length
from logbar.progress import ProgressStyle


class TestDrawing(unittest.TestCase):
    def test_cell_bar_renderer_draws_partial_frontier(self):
        renderer = CellBarRenderer(fill_char="█", empty_char="-")
        result = renderer.render_units(total_cells=4, filled_units=10)

        self.assertEqual(result.plain, "█▎--")
        self.assertEqual(result.rendered, result.plain)

    def test_progress_style_render_units_keeps_bar_width(self):
        style = ProgressStyle(name="test", empty_char="·")
        plain, rendered = style.render_units(total_cells=6, filled_units=17)

        self.assertEqual(plain, "██▏···")
        self.assertEqual(rendered, plain)
        self.assertEqual(len(plain), 6)

    def test_ansi_helpers_share_visibility_and_truncation_rules(self):
        text = "\033[31mred\033[0m-blue"

        self.assertEqual(strip_ansi(text), "red-blue")
        self.assertEqual(visible_length(text), 8)
        self.assertEqual(strip_ansi(truncate_ansi(text, 5)), "red-b")

    def test_ansi_helpers_measure_wide_combining_and_flag_clusters(self):
        text = "\033[31m界🙂e\u0301🇺🇸\033[0m"

        self.assertEqual(strip_ansi(text), "界🙂e\u0301🇺🇸")
        self.assertEqual(visible_length(text), 7)
        self.assertEqual(strip_ansi(truncate_ansi(text, 4)), "界🙂")
        self.assertEqual(strip_ansi(truncate_ansi(text, 5)), "界🙂e\u0301")

    def test_ansi_helpers_keep_zwj_emoji_clusters_atomic(self):
        text = "A👨‍👩‍👧‍👦B"

        self.assertEqual(visible_length(text), 4)
        self.assertEqual(strip_ansi(truncate_ansi(text, 3)), "A👨‍👩‍👧‍👦")

    def test_ansi_helpers_expand_tabs_to_terminal_stops(self):
        text = "A\tB"

        self.assertEqual(visible_length(text), 9)
        self.assertEqual(strip_ansi(truncate_ansi(text, 7)), "A")
        self.assertEqual(strip_ansi(truncate_ansi(text, 8)), "A\t")
        self.assertEqual(strip_ansi(truncate_ansi(text, 9)), "A\tB")
