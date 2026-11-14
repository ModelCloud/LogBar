# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Regression coverage for issue #79 memory leaks and unbounded buffers."""

from __future__ import annotations

import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
import unittest
from unittest import mock

from logbar import LogBar
from logbar import logbar as logbar_module
from logbar.region import LogRegion
from logbar.region_logger import RegionLogBar


def _pty_env() -> dict[str, str]:
    """Return an environment that forces interactive rendering inside a pty."""

    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("CODEX_", "PYTEST", "NO_COLOR", "ANSI_COLORS_DISABLED")):
            env.pop(key, None)
    env.update(
        {
            "TERM": "xterm",
            "LOGBAR_FORCE_ANSI": "1",
            "LOGBAR_FORCE_PROGRESS": "1",
        }
    )
    return env


def _run_in_pty(script: str, *, size: tuple[int, int] = (80, 24), timeout: float = 30.0):
    """Run ``script`` under a real pty and return ``(returncode, raw_bytes)``."""

    master_fd, slave_fd = pty.openpty()
    winsize = struct.pack("HHHH", size[1], size[0], 0, 0)
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=_pty_env(),
        close_fds=True,
    )
    os.close(slave_fd)
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                raise AssertionError("pty child timed out")
            ready, _, _ = select.select([master_fd], [], [], remaining)
            if not ready:
                process.kill()
                raise AssertionError("pty child produced no output")
            try:
                data = os.read(master_fd, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    finally:
        os.close(master_fd)
    return process.wait(timeout=timeout), b"".join(chunks)


class TestProgressBarDetach(unittest.TestCase):
    """Bars must detach when iteration stops early."""

    def test_break_and_exception_release_bars(self):
        """``break`` and exceptions must close and detach every bar."""

        script = r"""
import gc
import weakref

from logbar import LogBar
from logbar import logbar as logbar_module

log = LogBar.shared(override_logger=True)
refs = []

for _ in range(5):
    bar = log.pb(range(100000))
    for _ in bar:
        break
    refs.append(weakref.ref(bar))
    del bar

for _ in range(5):
    bar = log.pb(range(100000))
    try:
        for _ in bar:
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    refs.append(weakref.ref(bar))
    del bar

gc.collect()
state = logbar_module._coordinator_state()
print("ATTACHED", len(state._attached_progress_bars), flush=True)
print("ALIVE", sum(1 for ref in refs if ref() is not None), flush=True)
"""
        returncode, output = _run_in_pty(script, size=(80, 24))
        self.assertEqual(returncode, 0, msg=output[-2000:])
        self.assertIn(b"ATTACHED 0", output)
        self.assertIn(b"ALIVE 0", output)

    def test_iterating_flag_is_set(self):
        """The iteration guard must use ``_iterating`` so warnings can fire."""

        log = LogBar.shared(override_logger=True)
        bar = log.pb(range(3))
        iterator = iter(bar)
        try:
            next(iterator)
            self.assertTrue(bar._iterating)
        finally:
            iterator.close()

    def test_title_warning_fires_while_iterating(self):
        """Changing a title mid-iteration warns once the guard is correct."""

        log = LogBar.shared(override_logger=True)
        bar = log.pb(range(3))
        iterator = iter(bar)
        try:
            next(iterator)
            with mock.patch("logbar.progress.logger.warn") as warn:
                bar.title("mid-iteration title")
            warn.assert_called_once()
        finally:
            iterator.close()


class TestDeferredLogBuffer(unittest.TestCase):
    """Deferred log records must be bounded and must survive shutdown."""

    def setUp(self):
        self.log = LogBar.shared(override_logger=True)
        self.state = logbar_module._coordinator_state()
        self.state._deferred_log_records = []

    def tearDown(self):
        self.state._deferred_log_records = []

    def test_deferred_records_are_bounded(self):
        """A fullscreen footer must not accumulate unbounded log records."""

        with mock.patch.object(
            logbar_module,
            "_should_defer_log_output_locked",
            return_value=True,
        ):
            for index in range(5000):
                self.log.info("deferred %d", index)

        records = self.state._deferred_log_records
        self.assertLessEqual(len(records), logbar_module._DEFERRED_LOG_LIMIT)
        self.assertEqual(len(records), logbar_module._DEFERRED_LOG_LIMIT)

    def test_warning_and_above_survive_eviction(self):
        """Priority records must evict plain INFO records first."""

        with mock.patch.object(
            logbar_module,
            "_should_defer_log_output_locked",
            return_value=True,
        ):
            for index in range(5000):
                self.log.info("deferred %d", index)
            for index in range(100):
                self.log.warn("PRIORITY %03d", index)  # noqa: G010 - legacy API

        messages = [message for _level, message in self.state._deferred_log_records]
        self.assertEqual(sum(1 for message in messages if message.startswith("PRIORITY")), 100)

    def test_error_is_replayed_at_shutdown(self):
        """An ERROR buffered behind a fullscreen footer must still be printed."""

        script = r"""
from logbar import LogBar

log = LogBar.shared(override_logger=True)
bars = [log.pb(range(100)).title("bar%d" % index) for index in range(6)]
log.error("IMPORTANT")
raise SystemExit(1)
"""
        returncode, output = _run_in_pty(script, size=(80, 5))
        self.assertEqual(returncode, 1, msg=output[-2000:])
        self.assertIn(b"IMPORTANT", output)


class TestRegionScrollback(unittest.TestCase):
    """Region scrollback must be bounded instead of growing forever."""

    def test_log_region_respects_max_scrollback(self):
        """``LogRegion`` keeps only the newest ``max_scrollback`` rows."""

        region = LogRegion(max_scrollback=50)
        for index in range(1000):
            region.append_body_line(str(index))

        self.assertEqual(len(region.body_lines), 50)
        self.assertEqual(region.body_lines[-1], "999")
        self.assertEqual(region.body_lines[0], "950")

    def test_set_body_lines_respects_max_scrollback(self):
        """Replacing the body must also apply the scrollback cap."""

        region = LogRegion(max_scrollback=5)
        region.set_body_lines([str(index) for index in range(20)])
        self.assertEqual(region.body_lines, ["15", "16", "17", "18", "19"])

    def test_region_logger_default_is_bounded(self):
        """``RegionLogBar`` must inherit the bounded scrollback."""

        region = LogRegion(max_scrollback=25)
        logger = RegionLogBar("bounded", region)
        for index in range(500):
            logger.info("line %d", index)
        self.assertEqual(len(region.body_lines), 25)


class TestOnceDeduplication(unittest.TestCase):
    """``.once()`` must deduplicate on values, including unhashable ones."""

    def setUp(self):
        self.log = LogBar.shared(override_logger=True)
        self.log.history.clear()

    def tearDown(self):
        self.log.history.clear()

    def test_hash_collision_does_not_dedupe(self):
        """Values with equal hashes but different values must both pass."""

        self.assertTrue(self.log.history_add(-1))
        self.assertTrue(self.log.history_add(-2))

    def test_unhashable_message_is_supported(self):
        """Unhashable messages must not raise and must still deduplicate."""

        self.assertTrue(self.log.history_add(["a", "b"]))
        self.assertFalse(self.log.history_add(["a", "b"]))


class TestTqdmWrite(unittest.TestCase):
    """``tqdm.write`` must not paint over an active footer."""

    def test_write_redraws_active_stack(self):
        """Text written above a footer must be followed by a footer redraw."""

        script = r"""
from logbar import LogBar
from logbar.tqdm import tqdm

log = LogBar.shared(override_logger=True)
bar = tqdm(range(10), desc="BAR", total=10)
bar.set_postfix({"m": "SUBMARK"})
bar.draw(force=True)
tqdm.write("HELLO_WRITE")
bar.close()
"""
        returncode, output = _run_in_pty(script, size=(80, 24))
        self.assertEqual(returncode, 0, msg=output[-2000:])
        self.assertIn(b"HELLO_WRITE", output)
        tail = output.split(b"HELLO_WRITE", 1)[1]
        self.assertIn(b"SUBMARK", tail)


if __name__ == "__main__":
    unittest.main()
