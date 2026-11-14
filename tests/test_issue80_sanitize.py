# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Regression coverage for issue #80 terminal escape-sequence injection."""

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

from logbar import LogBar
from logbar.drawing import (
    ANSI_ESCAPE_RE,
    strip_ansi,
    visible_length,
)

OSC52 = "\x1b]52;c;Zm9vYmFy\x07"
OSC_TITLE = "\x1b]0;title\x07"
DCS = "\x1bP1;2;3qDATA\x1b\\"
CURSOR = "\x1b[2A\x1b[2K"


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
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", size[1], size[0], 0, 0))
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


class TestEscapeRegex(unittest.TestCase):
    """The shared ANSI matcher must understand OSC and DCS sequences."""

    def test_strip_ansi_removes_osc(self):
        self.assertEqual(strip_ansi(f"a{OSC_TITLE}b"), "ab")
        self.assertEqual(strip_ansi(OSC52), "")

    def test_strip_ansi_removes_dcs(self):
        self.assertEqual(strip_ansi(f"a{DCS}b"), "ab")

    def test_visible_length_ignores_osc_payload(self):
        self.assertEqual(visible_length(f"{OSC_TITLE}abc"), 3)
        self.assertEqual(visible_length(f"{OSC52}hello"), 5)

    def test_visible_length_ignores_cursor_movement(self):
        self.assertEqual(visible_length(f"{CURSOR}abc"), 3)

    def test_regex_matches_osc_terminator_variants(self):
        self.assertTrue(ANSI_ESCAPE_RE.fullmatch("\x1b]0;x\x07"))
        self.assertTrue(ANSI_ESCAPE_RE.fullmatch("\x1b]0;x\x1b\\"))


class TestSanitizeText(unittest.TestCase):
    """Titles, subtitles and messages must be sanitized before rendering."""

    def setUp(self):
        from logbar.drawing import sanitize_text

        self.sanitize_text = sanitize_text

    def test_keeps_sgr_color(self):
        colored = "\x1b[31mRED\x1b[0m"
        self.assertEqual(self.sanitize_text(colored), colored)

    def test_strips_osc_dcs_and_cursor(self):
        self.assertEqual(self.sanitize_text(f"a{OSC52}b"), "ab")
        self.assertEqual(self.sanitize_text(f"a{DCS}b"), "ab")
        self.assertEqual(self.sanitize_text(f"a{CURSOR}b"), "ab")

    def test_collapses_newlines(self):
        self.assertEqual(self.sanitize_text("A\nB"), "A B")
        self.assertEqual(self.sanitize_text("A\rB"), "A B")
        self.assertEqual(self.sanitize_text("A\tB"), "A B")

    def test_headless_strips_sgr_too(self):
        self.assertEqual(self.sanitize_text("\x1b[31mRED\x1b[0m", allow_sgr=False), "RED")

    def test_clean_text_is_unchanged(self):
        self.assertEqual(self.sanitize_text("plain text"), "plain text")


class TestLogInjection(unittest.TestCase):
    """Raw pty bytes must not contain injected escape sequences."""

    def test_log_messages_are_sanitized(self):
        script = r"""
from logbar import LogBar

log = LogBar.shared(override_logger=True)
log.info("osc52 \x1b]52;c;Zm9vYmFy\x07 tail")
log.info("osc0 \x1b]0;title\x07 tail")
log.info("dcs \x1bP1;2;3qDATA\x1b\\ tail")
log.info("cursor \x1b[2A\x1b[2K tail")
log.info("carriage safe\rEVIL tail")
log.info("color \x1b[31mRED\x1b[0m tail")
"""
        returncode, output = _run_in_pty(script, size=(80, 24))
        self.assertEqual(returncode, 0, msg=output[-2000:])
        self.assertNotIn(OSC52.encode(), output)
        self.assertNotIn(OSC_TITLE.encode(), output)
        self.assertNotIn(DCS.encode(), output)
        self.assertNotIn(CURSOR.encode(), output)
        self.assertNotIn(b"safe\rEVIL", output)
        self.assertIn(b"\x1b[31mRED", output)
        self.assertIn(b"osc52", output)

    def test_headless_strips_sgr_and_osc(self):
        script = r"""
from logbar import LogBar

log = LogBar.shared(override_logger=True)
log.info("color \x1b[31mRED\x1b[0m \x1b]0;title\x07 tail")
"""
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("CODEX_", "PYTEST", "NO_COLOR", "ANSI_COLORS_DISABLED")):
                env.pop(key, None)
        env.update({"CI": "1", "TERM": "xterm", "LOGBAR_FORCE_ANSI": "1"})
        env.pop("LOGBAR_FORCE_PROGRESS", None)
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
        self.assertNotIn(b"\x1b[31m", result.stdout)
        self.assertNotIn(OSC_TITLE.encode(), result.stdout)
        self.assertIn(b"RED", result.stdout)


class TestProgressInjection(unittest.TestCase):
    """Titles, subtitles and tqdm fields must not inject escape sequences."""

    def test_title_newline_is_collapsed(self):
        log = LogBar.shared(override_logger=True)
        bar = log.pb(range(2))
        try:
            bar.title("T\x1b]0;evil\x07A\nB")
            self.assertEqual(bar._title, "TA B")
            self.assertEqual(bar._title_width, 4)
        finally:
            bar.close()

    def test_title_and_subtitle_sanitized_in_pty(self):
        script = r"""
from logbar import LogBar

log = LogBar.shared(override_logger=True)
bar = log.pb(range(2)).title("T\x1b]0;evil\x07A\nB")
bar.subtitle("S\x1b[2A\x1b[2KX")
bar.draw(force=True)
bar.close()
"""
        returncode, output = _run_in_pty(script, size=(80, 24))
        self.assertEqual(returncode, 0, msg=output[-2000:])
        self.assertNotIn(b"\x1b]0;evil\x07", output)
        self.assertNotIn(CURSOR.encode(), output)
        self.assertNotIn(b"A\nB", output)
        self.assertIn(b"A B", output)
        self.assertIn(b"SX", output)

    def test_tqdm_desc_and_postfix_sanitized(self):
        script = r"""
from logbar import LogBar
from logbar.tqdm import tqdm

log = LogBar.shared(override_logger=True)
bar = tqdm(
    range(2),
    desc="D\x1b]0;evil\x07",
    postfix={"k": "\x1b[2A\x1b[2K"},
)
bar.draw(force=True)
bar.close()
"""
        returncode, output = _run_in_pty(script, size=(80, 24))
        self.assertEqual(returncode, 0, msg=output[-2000:])
        self.assertNotIn(b"\x1b]0;evil\x07", output)
        self.assertNotIn(CURSOR.encode(), output)
        self.assertIn(b"k=", output)


if __name__ == "__main__":
    unittest.main()
