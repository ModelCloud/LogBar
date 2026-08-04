# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Tests for headless / AI-agent / notebook auto-detection."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from logbar.terminal import (
    _is_headless_environment,
    render_backend_state,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestHeadlessDetection(unittest.TestCase):
    """Unit coverage for the environment-based headless detector."""

    def setUp(self):
        """Expose the detector to the test process by faking non-pytest mode."""

        self._headless_patch = patch("logbar.terminal._running_under_pytest", return_value=False)
        self._headless_patch.start()

    def tearDown(self):
        """Restore the pytest-detection patch."""

        self._headless_patch.stop()

    def test_force_progress_disables_headless_detection(self):
        """``LOGBAR_FORCE_PROGRESS=1`` keeps the UI enabled."""

        with patch.dict(
            "logbar.terminal.os.environ",
            {"CI": "1", "LOGBAR_FORCE_PROGRESS": "1"},
            clear=True,
        ):
            self.assertFalse(_is_headless_environment())

    def test_disable_headless_detection_flag(self):
        """``LOGBAR_DISABLE_HEADLESS_DETECTION=1`` keeps the UI enabled."""

        with patch.dict(
            "logbar.terminal.os.environ",
            {"CI": "1", "LOGBAR_DISABLE_HEADLESS_DETECTION": "1"},
            clear=True,
        ):
            self.assertFalse(_is_headless_environment())

    def test_ci_env_is_headless(self):
        """CI variables are treated as non-interactive headless backends."""

        with patch.dict("logbar.terminal.os.environ", {"CI": "true"}, clear=True):
            self.assertTrue(_is_headless_environment())

    def test_devin_env_is_headless(self):
        """Devin session variables disable progress redrawing."""

        with patch.dict(
            "logbar.terminal.os.environ",
            {"DEVIN_OUTPOST_SESSION_ID": "devin-123"},
            clear=True,
        ):
            self.assertTrue(_is_headless_environment())

    def test_codex_env_is_headless(self):
        """Codex session variables disable progress redrawing."""

        with patch.dict(
            "logbar.terminal.os.environ",
            {"CODEX_HOME": "/tmp/codex"},
            clear=True,
        ):
            self.assertTrue(_is_headless_environment())

    def test_jupyter_kernel_env_is_headless(self):
        """Jupyter kernel parent markers disable progress redrawing."""

        with patch.dict(
            "logbar.terminal.os.environ",
            {"JPY_PARENT_PID": "12345"},
            clear=True,
        ):
            self.assertTrue(_is_headless_environment())

    def test_dumb_term_is_headless(self):
        """A ``TERM=dumb`` terminal disables progress redrawing."""

        with patch.dict("logbar.terminal.os.environ", {"TERM": "dumb"}, clear=True):
            self.assertTrue(_is_headless_environment())

    def test_headless_honors_force_ansi(self):
        """``LOGBAR_FORCE_ANSI=1`` still enables ANSI color in headless backends."""

        class NonTTYStream:
            def isatty(self):
                return False

        with patch.dict(
            "logbar.terminal.os.environ",
            {"CI": "1", "LOGBAR_FORCE_ANSI": "1"},
            clear=True,
        ):
            state = render_backend_state(stream=NonTTYStream(), size_provider=lambda: (80, 24))

        self.assertTrue(state.headless)
        self.assertTrue(state.supports_ansi)
        self.assertTrue(state.supports_styling)
        self.assertFalse(state.supports_cursor)

    def test_notebook_backend_is_headless(self):
        """The backend state reports ``headless=True`` for notebook targets."""

        state = render_backend_state(notebook=True)
        self.assertTrue(state.headless)
        self.assertFalse(state.supports_cursor)
        self.assertFalse(state.supports_ansi)
        self.assertFalse(state.supports_styling)

    def test_plain_terminal_is_not_headless(self):
        """A clean, non-CI, non-agent environment is not headless."""

        with patch.dict("logbar.terminal.os.environ", {}, clear=True):
            self.assertFalse(_is_headless_environment())


class TestHeadlessProgressBehavior(unittest.TestCase):
    """End-to-end checks that headless mode suppresses progress output."""

    _PROGRESS_SCRIPT = """
import sys
from io import StringIO
sys.stdout = StringIO()
# Import after replacing stdout so any import-time log lands in the buffer.
from logbar.progress import ProgressBar

for _ in ProgressBar(range(5)):
    pass
out = sys.stdout.getvalue()
print("HAS_LOG", "LogBar: headless" in out, file=sys.stderr)
print("HAS_PROGRESS", "[1 of 5]" in out or "100.0%" in out, file=sys.stderr)
"""

    @staticmethod
    def _run_progress_in_subprocess(env: dict) -> subprocess.CompletedProcess:
        """Run the progress script with the supplied environment."""

        return subprocess.run(
            [sys.executable, "-c", TestHeadlessProgressBehavior._PROGRESS_SCRIPT],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

    def test_devin_terminal_suppresses_progress_and_logs_state(self):
        """A Devin-marked subprocess logs the headless state and skips redraws."""

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_ROOT),
            "DEVIN_OUTPOST_SESSION_ID": "devin-test-123",
        }
        result = self._run_progress_in_subprocess(env)
        self.assertIn("HAS_LOG True", result.stderr)
        self.assertIn("HAS_PROGRESS False", result.stderr)

    def test_codex_terminal_suppresses_progress_and_logs_state(self):
        """A Codex-marked subprocess logs the headless state and skips redraws."""

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_ROOT),
            "CODEX_HOME": "/tmp/codex-test",
        }
        result = self._run_progress_in_subprocess(env)
        self.assertIn("HAS_LOG True", result.stderr)
        self.assertIn("HAS_PROGRESS False", result.stderr)

    def test_plain_terminal_renders_progress_and_no_headless_log(self):
        """A clean subprocess renders progress and does not emit the headless log."""

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_ROOT),
        }
        result = self._run_progress_in_subprocess(env)
        self.assertIn("HAS_LOG False", result.stderr)
        self.assertIn("HAS_PROGRESS True", result.stderr)

    def test_logbar_shared_emits_single_headless_log(self):
        """``LogBar.shared()`` emits the headless state once in a headless shell."""

        script = """
import sys
from io import StringIO
sys.stdout = StringIO()
from logbar import LogBar

log = LogBar.shared()
log = LogBar.shared()  # second call should be idempotent
out = sys.stdout.getvalue()
# The single log line should appear exactly once.
print("COUNT", out.count("headless/CI mode"), file=sys.stderr)
"""
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(REPO_ROOT),
            "DEVIN_OUTPOST_SESSION_ID": "devin-test-123",
        }
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("COUNT 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
