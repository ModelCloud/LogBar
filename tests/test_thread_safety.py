# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Focused concurrency checks for free-threaded LogBar API usage."""

from __future__ import annotations

import queue
import sys
import threading
import unittest
from unittest import mock

from logbar.columns import ColumnsPrinter
from logbar.logbar import LEVEL
from logbar.progress import ProgressBar, ProgressStyle
from logbar.session import RegionScreenSession
from logbar.terminal import RenderBackendState
from tests._stream_helpers import FakeTTY


def _nogil_enabled() -> bool:
    """Return whether the current interpreter is actually running with the GIL disabled."""

    gil_probe = getattr(sys, "_is_gil_enabled", None)
    if callable(gil_probe):
        return not gil_probe()
    return str(sys._xoptions.get("gil", "")).strip() == "0"


class _RecordingLogger:
    """Small logger stub that records rendered rows for thread-safety tests."""

    def __init__(self) -> None:
        self.rows: list[tuple[object, str]] = []
        self._lock = threading.Lock()

    def _process(self, level, row) -> None:
        with self._lock:
            self.rows.append((level, str(row)))


@unittest.skipUnless(
    _nogil_enabled(),
    "requires a free-threaded runtime with the GIL disabled; run with `python -X gil=0 -m pytest ...`",
)
class TestThreadSafety(unittest.TestCase):
    """Concurrency coverage for exposed rendering-facing APIs."""

    def test_progress_bar_public_mutations_and_draws_can_overlap(self):
        """Progress-bar state changes and draws should stay race-free."""

        backend_state = RenderBackendState(
            columns=80,
            lines=2,
            is_tty=False,
            notebook=False,
            supports_cursor=False,
            supports_ansi=False,
            supports_styling=False,
        )
        errors: "queue.Queue[BaseException]" = queue.Queue()
        barrier = threading.Barrier(3)

        with mock.patch("logbar.progress.render_backend_state", return_value=backend_state), \
             mock.patch("builtins.print"):
            pb = ProgressBar(200).manual()

            def mutate_title() -> None:
                try:
                    barrier.wait()
                    for idx in range(50):
                        pb.title(f"title-{idx}")
                        pb.subtitle(f"sub-{idx}")
                except BaseException as exc:  # pragma: no cover - surfaced below
                    errors.put(exc)

            def advance() -> None:
                try:
                    barrier.wait()
                    for _ in range(50):
                        pb.next()
                        pb.draw(force=True)
                except BaseException as exc:  # pragma: no cover - surfaced below
                    errors.put(exc)

            def restyle() -> None:
                try:
                    barrier.wait()
                    for idx in range(50):
                        pb.output_interval((idx % 3) + 1)
                        pb.style("mono")
                        pb.fill("█", empty="-")
                except BaseException as exc:  # pragma: no cover - surfaced below
                    errors.put(exc)

            threads = [
                threading.Thread(target=mutate_title),
                threading.Thread(target=advance),
                threading.Thread(target=restyle),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertTrue(errors.empty(), list(errors.queue))
            self.assertEqual(pb.step(), 50)
            self.assertFalse(pb.closed)

            pb.close()

    def test_progress_style_registry_calls_can_overlap(self):
        """Global style registry reads/writes should stay race-free."""

        errors: "queue.Queue[BaseException]" = queue.Queue()
        barrier = threading.Barrier(3)

        def register_styles() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    ProgressBar.register_style(
                        ProgressStyle(
                            name=f"thread-style-{idx}",
                            fill_char="*",
                            empty_char=".",
                        )
                    )
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def swap_default_style() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    ProgressBar.set_default_style("mono" if idx % 2 == 0 else "emerald_glow")
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def read_styles() -> None:
            try:
                barrier.wait()
                for _ in range(25):
                    ProgressBar.available_styles()
                    ProgressBar.default_style()
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        threads = [
            threading.Thread(target=register_styles),
            threading.Thread(target=swap_default_style),
            threading.Thread(target=read_styles),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertTrue(errors.empty(), list(errors.queue))
        self.assertIn("mono", ProgressBar.available_styles())

    def test_columns_printer_updates_and_renders_can_overlap(self):
        """Column width bookkeeping should stay coherent under concurrent calls."""

        logger = _RecordingLogger()
        printer = ColumnsPrinter(
            logger=logger,
            headers=("task", "state"),
            level_enum=LEVEL,
            level_max_length=5,
            terminal_size_provider=lambda: (60, 10),
        )
        errors: "queue.Queue[BaseException]" = queue.Queue()
        barrier = threading.Barrier(3)

        def emit_rows() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    printer.info(f"job-{idx}", "active")
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def simulate_rows() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    printer.info.simulate(f"sim-{idx}", "queued")
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def update_layout() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    printer.update({
                        "task": {"width": 8 + (idx % 3)},
                        "state": {"width": "fit"},
                    })
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        threads = [
            threading.Thread(target=emit_rows),
            threading.Thread(target=simulate_rows),
            threading.Thread(target=update_layout),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertTrue(errors.empty(), list(errors.queue))
        self.assertTrue(logger.rows)

    def test_split_session_log_footer_and_render_calls_can_overlap(self):
        """Split-session logger and footer operations should stay serialized."""

        session = RegionScreenSession.columns(
            "left",
            "right",
            stream=FakeTTY(),
            size_provider=lambda: (40, 6),
            use_alternate_screen=False,
            auto_render=False,
        )
        left = session.create_logger("left", supports_ansi=False)
        right = session.create_logger("right", supports_ansi=False)
        left.setLevel("INFO")
        right.setLevel("INFO")

        errors: "queue.Queue[BaseException]" = queue.Queue()
        barrier = threading.Barrier(3)

        def emit_logs() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    left.info("left-%s", idx)
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def mutate_footer() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    right.set_footer_lines([f"footer-{idx}"])
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def render_loop() -> None:
            try:
                barrier.wait()
                for _ in range(25):
                    session.render()
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        threads = [
            threading.Thread(target=emit_logs),
            threading.Thread(target=mutate_footer),
            threading.Thread(target=render_loop),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertTrue(errors.empty(), list(errors.queue))
        rows = session.render()
        self.assertTrue(any("left-" in row for row in rows))
        self.assertTrue(any("footer-" in row for row in rows))

        session.close()

    def test_split_session_progress_attach_draw_and_refresh_can_overlap(self):
        """Pane-local progress/session operations should stay race-free."""

        session = RegionScreenSession.columns(
            "left",
            "right",
            stream=FakeTTY(),
            size_provider=lambda: (40, 6),
            use_alternate_screen=False,
            auto_render=False,
        )
        pb = session.pb(range(100), region_id="left", output_interval=1).manual()
        errors: "queue.Queue[BaseException]" = queue.Queue()
        barrier = threading.Barrier(3)

        def toggle_attachment() -> None:
            try:
                barrier.wait()
                for _ in range(10):
                    pb.detach()
                    pb.attach()
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def mutate_and_draw() -> None:
            try:
                barrier.wait()
                for idx in range(25):
                    pb.title(f"left-{idx}")
                    pb.next()
                    pb.draw(force=True)
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        def refresh_session() -> None:
            try:
                barrier.wait()
                for _ in range(25):
                    session.refresh_progress(force=True)
            except BaseException as exc:  # pragma: no cover - surfaced below
                errors.put(exc)

        threads = [
            threading.Thread(target=toggle_attachment),
            threading.Thread(target=mutate_and_draw),
            threading.Thread(target=refresh_session),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertTrue(errors.empty(), list(errors.queue))
        rows = session.render()
        self.assertTrue(any("left-" in row for row in rows))

        pb.close()
        session.close()
