# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Regression coverage for issue #78: progress counters must not lose updates."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
from unittest import mock

from logbar import LogBar
from logbar.tqdm import tqdm

THREADS = 8
STEPS = 20_000


def _hammer(bar, operation) -> int:
    """Run ``operation`` from ``THREADS`` threads and return the final count."""

    barrier = threading.Barrier(THREADS)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            for _ in range(STEPS):
                operation(bar)
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if errors:
        raise errors[0]
    return bar.current_iter_step


class TestCounterThreadSafety(unittest.TestCase):
    """Concurrent counter updates must never be lost."""

    def setUp(self):
        self.log = LogBar.shared(override_logger=True)
        self.expected = THREADS * STEPS
        # Force frequent thread switches so an unguarded read-modify-write
        # loses updates deterministically instead of only under load. This is
        # a no-op on free-threaded builds, where switches are always possible.
        self._switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)

    def tearDown(self):
        sys.setswitchinterval(self._switch_interval)

    def test_next_exact_in_headless_mode(self):
        """Headless mode skips the render lock, so the counter lock must hold."""

        bar = self.log.pb(range(10)).manual()
        try:
            bar._headless = True
            self.assertEqual(_hammer(bar, lambda target: target.next()), self.expected)
        finally:
            bar.close()

    def test_next_exact_in_render_mode(self):
        """The render-lock path must stay exact as well."""

        bar = self.log.pb(range(10)).manual()
        try:
            bar._headless = False
            self.assertEqual(_hammer(bar, lambda target: target.next()), self.expected)
        finally:
            bar.close()

    def test_tqdm_update_exact_in_headless_mode(self):
        """``tqdm.update`` is unlocked in every mode without the counter lock."""

        bar = tqdm(range(10), total=10)
        try:
            bar._headless = True
            self.assertEqual(_hammer(bar, lambda target: target.update(1)), self.expected)
        finally:
            bar.close()

    def test_tqdm_update_exact_in_render_mode(self):
        """The drawing path must stay exact as well."""

        bar = tqdm(range(10), total=10)
        try:
            bar._headless = False
            # Painting 80k frames is not the subject of this test; the counter
            # and lock ordering is. Suppress only the paint.
            with mock.patch.object(tqdm, "draw", lambda *args, **kwargs: None):
                self.assertEqual(_hammer(bar, lambda target: target.update(1)), self.expected)
        finally:
            bar.close()

    def test_n_setter_keeps_last_written_value(self):
        """The ``n`` setter must never tear a value or deadlock against updates."""

        bar = tqdm(range(10), total=10)
        written: list[int] = [index * STEPS + step for index in range(THREADS) for step in range(STEPS)]
        barrier = threading.Barrier(THREADS)

        def worker(base: int) -> None:
            barrier.wait()
            for step in range(STEPS):
                bar.n = base * STEPS + step

        threads = [
            threading.Thread(target=worker, args=(index,))
            for index in range(THREADS)
        ]
        try:
            bar._headless = True
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertIn(bar.n, set(written))
        finally:
            bar.close()

    def test_update_and_next_share_one_counter(self):
        """Mixed writers must still add up exactly."""

        bar = tqdm(range(10), total=10)
        barrier = threading.Barrier(THREADS)

        def worker(use_update: bool) -> None:
            barrier.wait()
            for _ in range(STEPS):
                if use_update:
                    bar.update(1)
                else:
                    bar.next()

        threads = [
            threading.Thread(target=worker, args=(index % 2 == 0,))
            for index in range(THREADS)
        ]
        try:
            bar._headless = True
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(bar.current_iter_step, self.expected)
        finally:
            bar.close()


class TestHeadlessCounterSubprocess(unittest.TestCase):
    """Reproduce the CI-style headless path in a fresh interpreter."""

    def test_ci_headless_counters_are_exact(self):
        """``CI=1`` makes the bar headless; counts must still be exact."""

        script = f"""
import sys
import threading

from logbar import LogBar
from logbar.tqdm import tqdm

sys.setswitchinterval(1e-6)

log = LogBar.shared(override_logger=True)
threads, steps = {THREADS}, {STEPS}
expected = threads * steps

def run(bar, op):
    def work():
        for _ in range(steps):
            op(bar)
    workers = [threading.Thread(target=work) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return bar.current_iter_step

bar = log.pb(range(10)).manual()
print("headless", bar._headless, flush=True)
print("NEXT", run(bar, lambda target: target.next()), expected, flush=True)
bar.close()

bar = tqdm(range(10), total=10)
print("UPDATE", run(bar, lambda target: target.update(1)), expected, flush=True)
bar.close()
"""
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("PYTEST", "CODEX_", "NO_COLOR")):
                env.pop(key, None)
        env.update({"CI": "1", "TERM": "xterm"})
        env.pop("LOGBAR_FORCE_PROGRESS", None)
        env.pop("LOGBAR_DISABLE_HEADLESS_DETECTION", None)

        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
        self.assertIn("headless True", result.stdout)
        expected = THREADS * STEPS
        self.assertIn(f"NEXT {expected} {expected}", result.stdout)
        self.assertIn(f"UPDATE {expected} {expected}", result.stdout)


if __name__ == "__main__":
    unittest.main()
