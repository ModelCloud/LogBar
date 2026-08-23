# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Stress LogBar while a real terminal changes size underneath it."""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import textwrap
import time
import unittest
from pathlib import Path


_OBSERVED_SIZE_RE = re.compile(r"observed resize (\d+)x(\d+)")
_PTY_WORKER_ENV = "LOGBAR_PTY_RESIZE_WORKER"


class TestDynamicPTYResize(unittest.TestCase):
    """Exercise logging, progress, and tables while resizing a live PTY."""

    def test_logging_progress_and_tables_survive_dynamic_resize(self):
        """Keep rendering after repeated macOS-style PTY window-size changes."""

        if not hasattr(pty, "fork") or not hasattr(termios, "TIOCSWINSZ"):
            self.skipTest("PTY window resizing is unavailable on this platform")

        if os.environ.get(_PTY_WORKER_ENV) != "1":
            # pytest-xdist workers may have support threads. Run forkpty in a
            # fresh interpreter that has not started those threads.
            worker_env = dict(os.environ)
            worker_env[_PTY_WORKER_ENV] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-W",
                    "error",
                    "-m",
                    "tests.test_pty_resize",
                ],
                cwd=Path(__file__).resolve().parent.parent,
                env=worker_env,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                msg=f"PTY resize worker failed:\n{result.stdout}{result.stderr}",
            )
            return

        child_script = textwrap.dedent(
            """
            import time

            from logbar import LogBar
            from logbar.terminal import terminal_size


            log = LogBar.shared(override_logger=True)
            table = log.columns(cols=("step", "event", "details"))
            progress = log.pb(range(48)).title("resizing-progress").manual()
            previous_size = None

            try:
                for step in range(48):
                    current_size = terminal_size()
                    if current_size != previous_size:
                        log.info("observed resize %sx%s", *current_size)
                        previous_size = current_size

                    progress.current_iter_step = step
                    progress.draw(force=True)
                    table.info(str(step), "table", f"dynamic width sample {step}")
                    log.info("dynamic log %02d", step)
                    time.sleep(0.04)
            finally:
                progress.close()

            print("RESIZE_DONE", flush=True)
            """
        )

        child_env = dict(os.environ)
        child_env["LOGBAR_FORCE_PROGRESS"] = "1"
        child_env["LOGBAR_FORCE_ANSI"] = "1"
        child_env["TERM"] = "xterm"
        child_env.pop("PYTEST_CURRENT_TEST", None)

        pid, master_fd = pty.fork()
        if pid == pty.CHILD:
            os.execvpe(
                sys.executable,
                [sys.executable, "-c", child_script],
                child_env,
            )

        sizes = (
            (80, 24),
            (32, 8),
            (100, 30),
            (45, 12),
            (120, 40),
            (28, 6),
            (90, 18),
        )

        def resize(columns: int, lines: int) -> None:
            """Apply a new window size to the child terminal."""

            payload = struct.pack("HHHH", lines, columns, 0, 0)
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, payload)

        output = bytearray()
        status = None
        eof = False
        next_resize = time.monotonic()
        resize_index = 0
        deadline = time.monotonic() + 8.0

        try:
            while time.monotonic() < deadline:
                now = time.monotonic()
                if resize_index < len(sizes) and now >= next_resize:
                    resize(*sizes[resize_index])
                    resize_index += 1
                    next_resize = now + 0.12

                readable = []
                if not eof:
                    readable, _, _ = select.select([master_fd], [], [], 0.05)
                if readable:
                    try:
                        chunk = os.read(master_fd, 65536)
                        if chunk:
                            output.extend(chunk)
                        else:
                            eof = True
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        eof = True

                if status is None:
                    waited_pid, waited_status = os.waitpid(pid, os.WNOHANG)
                    if waited_pid == 0:
                        continue
                    status = waited_status

                if status is not None and (eof or not readable):
                    break
        finally:
            if status is None:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
                _, status = os.waitpid(pid, 0)
            os.close(master_fd)

        transcript = output.decode("utf-8", errors="replace")
        exit_code = os.waitstatus_to_exitcode(status)
        observed_sizes = set(_OBSERVED_SIZE_RE.findall(transcript))

        self.assertEqual(exit_code, 0, msg=transcript)
        self.assertGreaterEqual(resize_index, 5)
        self.assertGreaterEqual(len(observed_sizes), 3, msg=transcript)
        self.assertIn("dynamic log", transcript)
        self.assertIn("dynamic width sample", transcript)
        self.assertIn("RESIZE_DONE", transcript)
        self.assertNotIn("Traceback", transcript)


if __name__ == "__main__":
    unittest.main()
