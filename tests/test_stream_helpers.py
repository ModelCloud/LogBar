# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Regression tests for the shared test-stream helpers."""

from __future__ import annotations

import unittest

from tests._stream_helpers import MirroredTTY


class FailingMirror:
    """Mirror that can fail while flushing or closing."""

    def __init__(self, *, fail_flush: bool = False, fail_close: bool = False):
        self.fail_flush = fail_flush
        self.fail_close = fail_close
        self.closed = False

    def flush(self):
        if self.fail_flush:
            raise RuntimeError("mirror flush failed")

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("mirror close failed")


class TestMirroredTTYClose(unittest.TestCase):
    """Verify mirror failures cannot prevent either stream from closing."""

    def test_close_closes_both_streams(self):
        mirror = FailingMirror()
        stream = MirroredTTY(mirror)

        stream.close()

        self.assertTrue(stream.closed)
        self.assertTrue(mirror.closed)

    def test_flush_exception_propagates_after_both_streams_close(self):
        mirror = FailingMirror(fail_flush=True)
        stream = MirroredTTY(mirror)

        with self.assertRaisesRegex(RuntimeError, "mirror flush failed"):
            stream.close()

        self.assertTrue(stream.closed)
        self.assertTrue(mirror.closed)

    def test_close_exception_propagates_after_both_streams_close(self):
        mirror = FailingMirror(fail_close=True)
        stream = MirroredTTY(mirror)

        with self.assertRaisesRegex(RuntimeError, "mirror close failed"):
            stream.close()

        self.assertTrue(stream.closed)
        self.assertTrue(mirror.closed)


if __name__ == "__main__":
    unittest.main()
