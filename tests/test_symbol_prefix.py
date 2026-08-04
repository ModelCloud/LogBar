# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Coverage for the optional colored symbol log-level prefix feature."""

import os
import unittest
from unittest import mock

from logbar import LogBar
from logbar.logbar import (
    LEVEL,
    LEVEL_SYMBOLS,
    _level_max_length,
    _level_prefix,
    _level_width,
    _symbol_prefix_default,
    _terminal_supports_symbols,
)


class TestSymbolPrefix(unittest.TestCase):
    """Verify colored symbol prefixes and the text/symbol toggle."""

    def test_all_standard_levels_have_symbol(self):
        """Every standard level label has a corresponding colored symbol."""

        for level in LEVEL:
            self.assertIn(level.value, LEVEL_SYMBOLS)

    def test_symbol_prefix_is_shorter_than_text(self):
        """Symbol prefixes render using fewer visible columns than text."""

        for level in LEVEL:
            text_prefix = _level_prefix(level.value, True, False)
            sym_prefix = _level_prefix(level.value, True, True)
            self.assertTrue(len(sym_prefix) < len(text_prefix))

    def test_level_width_for_symbol_is_one(self):
        """Symbol prefixes reserve one visible column before the trailing space."""

        for level in LEVEL:
            self.assertEqual(_level_width(level.value, True), 1)

    def test_level_max_length_matches_mode(self):
        """Table width budget uses 1 for symbols and the longest text label otherwise."""

        self.assertEqual(_level_max_length(False), max(len(level.value) for level in LEVEL))
        self.assertEqual(_level_max_length(True), 1)

    def test_disable_symbol_prefix_env(self):
        """LOGBAR_DISABLE_SYMBOL_PREFIX defaults the toggle to disabled."""

        with mock.patch.dict(os.environ, {"LOGBAR_DISABLE_SYMBOL_PREFIX": "1"}, clear=True):
            self.assertFalse(_symbol_prefix_default())

    def test_force_symbol_prefix_overrides_disable(self):
        """LOGBAR_FORCE_SYMBOL_PREFIX wins over the disable flag."""

        env = {
            "LOGBAR_DISABLE_SYMBOL_PREFIX": "1",
            "LOGBAR_FORCE_SYMBOL_PREFIX": "1",
        }
        fake_stream = mock.Mock(isatty=mock.Mock(return_value=False))
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(
                _terminal_supports_symbols(supports_ansi=True, stream=fake_stream)
            )

    def test_terminal_supports_symbols_requires_ansi(self):
        """Symbol prefixes are not used when ANSI colors are unavailable."""

        fake_stream = mock.Mock(isatty=mock.Mock(return_value=True))
        self.assertFalse(_terminal_supports_symbols(supports_ansi=False, stream=fake_stream))

    def test_set_symbol_prefix_changes_behavior(self):
        """LogBar.set_symbol_prefix toggles the symbol-prefix mode."""

        log = LogBar("test_set_symbol_prefix_changes_behavior")
        self.assertTrue(log._symbol_prefix)
        log.set_symbol_prefix(False)
        self.assertFalse(log._symbol_prefix)
        log.set_symbol_prefix(True)
        self.assertTrue(log._symbol_prefix)
