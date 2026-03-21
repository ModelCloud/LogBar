# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import os
import subprocess
import random
import re
import sys
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from time import sleep
from unittest.mock import patch

from logbar import LogBar
from logbar import progress as progress_module
from logbar.progress import ProgressBar, TITLE_HIGHLIGHT_COLOR, ANSI_BOLD_RESET
from logbar.logbar import _active_progress_bars

log = LogBar.shared(override_logger=True)


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def extract_rendered_lines(buffer: str):
    """Split captured terminal output into visible lines without ANSI escapes."""

    cleaned = ANSI_ESCAPE_RE.sub('', buffer)
    lines = []
    accumulator = []

    for char in cleaned:
        if char == '\r':
            if accumulator:
                lines.append(''.join(accumulator))
                accumulator = []
        elif char == '\n':
            if accumulator:
                lines.append(''.join(accumulator))
                accumulator = []
        else:
            accumulator.append(char)

    if accumulator:
        lines.append(''.join(accumulator))

    return [line for line in lines if line]

def generate_expanding_str_a_to_z():
    """Build a grow-then-shrink sample set for dynamic title tests."""

    strings = []

    # Loop through the alphabet from 'A' to 'Z'
    for i in range(26):
        # Create a string from 'A' to the current character
        current_string = ''.join([chr(ord('A') + j) for j in range(i + 1)])
        strings.append(current_string)

    # Now, rev
    # erse the sequence from 'A...Y' to 'A'
    for i in range(25, 0, -1):
        # Create a string from 'A' to the current character
        current_string = ''.join([chr(ord('A') + j) for j in range(i)])
        strings.append(current_string)

    return strings

SAMPLES = generate_expanding_str_a_to_z()
REVERSED_SAMPLES = reversed(SAMPLES)

class TestProgress(unittest.TestCase):
    """Coverage for determinate and indeterminate progress rendering."""

    def setUp(self):
        """Reset environment-driven progress settings before each test."""

        self._saved_env = {
            "LOGBAR_ANIMATION": os.environ.get("LOGBAR_ANIMATION"),
            "LOGBAR_PROGRESS_OUTPUT_INTERVAL": os.environ.get("LOGBAR_PROGRESS_OUTPUT_INTERVAL"),
        }

        for key in self._saved_env:
            os.environ.pop(key, None)

        self._clear_progress_env_caches()

    def tearDown(self):
        """Restore environment-driven progress settings after each test."""

        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        self._clear_progress_env_caches()

    @staticmethod
    def _clear_progress_env_caches():
        """Clear cached environment readers so patched env vars take effect."""

        for helper_name in ("_env_animation_enabled", "_env_progress_output_interval"):
            helper = getattr(progress_module, helper_name, None)
            cache_clear = getattr(helper, "cache_clear", None)
            if callable(cache_clear):
                cache_clear()

    def test_title_fixed_subtitle_dynamic(self):
        """Allow a stable title with a subtitle that changes every frame."""

        pb = log.pb(SAMPLES).title("TITLE:").manual()
        for i in pb:
            pb.subtitle(f"[SUBTITLE: {i}]").draw()
            sleep(0.1)

    def test_title_dynamic_subtitle_fixed(self):
        """Allow a dynamic title while keeping the subtitle constant."""

        pb = log.pb(SAMPLES).subtitle("SUBTITLE: FIXED").manual()
        for i in pb:
            pb.title(f"[TITLE: {i}]").draw()
            sleep(0.1)

    def test_title_dynamic_subtitle_dynamic(self):
        """Support updating both title and subtitle during manual redraws."""

        pb = log.pb(SAMPLES).manual()
        count = 1
        for i in pb:
            log.info(f"random log: {count}")
            count += 1
            pb.title(f"[TITLE: {i}]").subtitle(f"[SUBTITLE: {i}]").draw()
            sleep(0.1)

    def test_range_manual(self):
        """Render a determinate bar manually over a numeric range."""

        pb = log.pb(range(100)).manual()
        for _ in pb:
            pb.draw()
            sleep(0.1)

    def test_range_auto_int(self):
        """Auto-expand integer totals into ranges for automatic rendering."""

        pb = log.pb(100)
        for _ in pb:
            sleep(0.1)

    def test_range_auto_dict(self):
        """Iterate mapping inputs through the convenience iterable adapter."""

        pb = log.pb({"1": 2, "2": 2})

        for _ in pb:
            sleep(0.1)

    def test_range_auto_disable_ui_left_steps(self):
        """Allow the left-side step label to be disabled."""

        pb = log.pb(100).set(show_left_steps=False)
        for _ in pb:
            sleep(0.1)

    def test_title(self):
        """Render a fixed title in automatic mode."""

        pb = log.pb(100).title("TITLE: FIXED")
        for _ in pb:
            sleep(0.1)

    def test_title_subtitle(self):
        """Render title and subtitle together in manual mode."""

        pb = log.pb(100).title("[TITLE: FIXED]").manual()
        for _ in pb:
            pb.subtitle(f"[SUBTITLE: FIXED]").draw()
            sleep(0.1)

    def test_title_animation_skips_ansi_sequences(self):
        """Animate visible title cells instead of ANSI escape bytes."""

        pb = log.pb(1).manual()
        ansi_title = "\033[31mRed\033[0mBlue"
        pb.title(ansi_title)
        pb._title_animation_period = 0.2
        pb._title_animation_start = 100.0

        with patch('logbar.progress.time.time', return_value=100.25):
            animated = pb._animated_text(ansi_title)

        match = re.search(re.escape(TITLE_HIGHLIGHT_COLOR) + r"(.)" + re.escape(ANSI_BOLD_RESET), animated)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "e")

        with redirect_stdout(StringIO()):
            pb.close()

    def test_title_animation_keeps_zwj_clusters_atomic(self):
        """Animate ZWJ emoji families as a single visible grapheme."""

        pb = log.pb(1).manual()
        title = "A👨‍👩‍👧‍👦B"
        pb.title(title)
        pb._title_animation_period = 0.1
        pb._title_animation_start = 100.0

        with patch('logbar.progress.time.time', return_value=100.2):
            animated = pb._animated_text(title)

        match = re.search(re.escape(TITLE_HIGHLIGHT_COLOR) + r"(.*?)" + re.escape(ANSI_BOLD_RESET), animated)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "👨‍👩‍👧‍👦")

        with redirect_stdout(StringIO()):
            pb.close()

    def test_title_animation_respects_logbar_animation_env(self):
        """Honor the global environment switch for title animation."""

        script = (
            "from types import SimpleNamespace\n"
            "import sys\n"
            "from logbar.progress import ProgressBar\n"
            "pb = ProgressBar(range(1)).manual()\n"
            "sys.stdout = SimpleNamespace(isatty=lambda: True, write=lambda *_: None, flush=lambda: None)\n"
            "sys.__stdout__.write('1\\n' if pb._should_animate_title() else '0\\n')\n"
        )

        enabled = subprocess.run(
            [sys.executable, "-c", script],
            cwd="/root/LogBar",
            capture_output=True,
            text=True,
            env={},
            check=True,
        )
        self.assertEqual(enabled.stdout.strip(), "1")

        disabled = subprocess.run(
            [sys.executable, "-c", script],
            cwd="/root/LogBar",
            capture_output=True,
            text=True,
            env={"LOGBAR_ANIMATION": "0"},
            check=True,
        )
        self.assertEqual(disabled.stdout.strip(), "0")

    def test_progress_output_interval_respects_env(self):
        """Seed new progress bars from the global output-interval env var."""

        cache_clear = progress_module._env_progress_output_interval.cache_clear

        with patch.dict(os.environ, {"LOGBAR_PROGRESS_OUTPUT_INTERVAL": "10"}):
            cache_clear()
            pb = ProgressBar(range(5))
            self.assertEqual(pb._output_interval, 10)
            with redirect_stdout(StringIO()):
                pb.close()

        cache_clear()

    def test_progress_output_interval_defaults_to_one(self):
        """Default progress output throttling to one logical step."""

        cache_clear = progress_module._env_progress_output_interval.cache_clear

        with patch.dict(os.environ, {}, clear=True):
            cache_clear()
            pb = ProgressBar(range(5))
            self.assertEqual(pb._output_interval, 1)
            with redirect_stdout(StringIO()):
                pb.close()

        cache_clear()

    def test_progress_output_interval_skips_intermediate_draws_but_flushes_final_step(self):
        """Skip intermediate frames while still forcing the final 100% snapshot."""

        columns = 96

        with patch('logbar.progress.terminal_size', return_value=(columns, 24)), \
             patch('logbar.logbar.terminal_size', return_value=(columns, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb = log.pb(15, output_interval=10).manual()
                for step in range(1, 16):
                    pb.current_iter_step = step
                    pb.draw()
                pb.close()

        lines = extract_rendered_lines(buffer.getvalue())
        progress_lines = [line for line in lines if "/15]" in line]

        self.assertTrue(any("[0/15]" in line for line in progress_lines))
        self.assertTrue(any("[10/15]" in line for line in progress_lines))
        self.assertTrue(any("[15/15]" in line and "100.0%" in line for line in progress_lines))
        self.assertFalse(any("[9/15]" in line for line in progress_lines))
        self.assertFalse(any("[14/15]" in line for line in progress_lines))

    def test_draw_respects_terminal_width(self):
        """Pad or truncate the rendered line to the detected terminal width."""

        pb = log.pb(100).title("TITLE").subtitle("SUBTITLE").manual()
        pb.current_iter_step = 50

        columns = 120
        with patch('logbar.progress.terminal_size', return_value=(columns, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()

        lines = extract_rendered_lines(buffer.getvalue())
        self.assertTrue(lines, "expected at least one rendered line")
        self.assertEqual(len(lines[-1]), columns)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_draw_respects_terminal_width_with_ansi_title_subtitle(self):
        """Measure ANSI-decorated titles by visible width, not raw byte length."""

        pb = log.pb(100).title("\033[31mTITLE\033[0m").subtitle("\033[32mSUB\033[0m").manual()
        pb.current_iter_step = 50

        columns = 80
        with patch('logbar.progress.terminal_size', return_value=(columns, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()

        lines = extract_rendered_lines(buffer.getvalue())
        self.assertTrue(lines, "expected at least one rendered line")
        self.assertEqual(len(lines[-1]), columns)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_time_estimate_accounts_for_last_item(self):
        """Estimate total time from completed work even on the final item."""

        pb = ProgressBar(range(3))
        pb.current_iter_step = 3
        pb.time = 0

        with patch('logbar.progress.time.time', return_value=10):
            estimate = pb.calc_time(pb.step())

        elapsed_str, total_str = [part.strip() for part in estimate.split("/", 1)]

        def to_seconds(value: str) -> int:
            """Normalize clock strings into seconds for easy comparison."""

            parts = [int(part) for part in value.split(":")]
            if len(parts) == 3:
                hours, minutes, seconds = parts
            elif len(parts) == 2:
                hours = 0
                minutes, seconds = parts
            else:
                hours = 0
                minutes = 0
                seconds = parts[0]
            return hours * 3600 + minutes * 60 + seconds

        self.assertGreater(to_seconds(total_str), to_seconds(elapsed_str))

    def test_draw_without_terminal_state(self):
        """Keep progress rendering alive when terminal size probing fails."""

        pb = log.pb(10).manual()
        pb.current_iter_step = 5

        with patch('logbar.terminal.shutil.get_terminal_size', side_effect=OSError()), \
             patch.dict('logbar.terminal.os.environ', {}, clear=True):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()

        output = buffer.getvalue()
        self.assertIn('[5/10]', output)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_progress_bars_stack_latest_bottom(self):
        """Keep later-attached bars rendered below earlier bars in the stack."""

        columns = 80
        pb1 = log.pb(100).title("PB1").manual()
        pb2 = log.pb(100).title("PB2").manual()

        pb1.current_iter_step = 25
        pb2.current_iter_step = 50

        with patch('logbar.progress.terminal_size', return_value=(columns, 24)):
            start = time.time()
            loop = 0
            while time.time() - start < 2.5:
                loop += 1
                pb1.current_iter_step = min(len(pb1), 25 + loop)
                pb1.draw()
                pb2.current_iter_step = min(len(pb2), 50 + loop * 2)
                pb2.draw()
                sleep(0.05)

            buffer = StringIO()
            with redirect_stdout(buffer):
                pb1.draw()
                pb2.draw()

        lines = extract_rendered_lines(buffer.getvalue())
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn('PB1', lines[-2])
        self.assertIn('PB2', lines[-1])

        with redirect_stdout(StringIO()):
            pb2.close()
            pb1.close()

    def test_detach_tolerates_missing_runtime_dependencies(self):
        """Detach bars safely across degraded runtime and finalization paths."""

        from logbar import progress as progress_module

        pb = log.pb(range(5)).manual()
        self.assertTrue(pb._attached)

        original_detach = progress_module.detach_progress_bar

        with patch.object(progress_module, "render_lock", new=None), \
             patch.object(progress_module, "detach_progress_bar", new=None), \
             patch.object(progress_module, "render_progress_stack", new=None):
            with redirect_stdout(StringIO()):
                pb.detach()

        self.assertFalse(pb._attached)

        with redirect_stdout(StringIO()):
            original_detach(pb)

        self.assertNotIn(pb, _active_progress_bars())

        pb_nonfinal = log.pb(range(3)).manual()
        self.assertTrue(pb_nonfinal._attached)

        def boom_detach(*args, **kwargs):
            """Simulate a detach implementation that always fails."""

            raise RuntimeError("boom")

        with patch.object(progress_module, "detach_progress_bar", new=boom_detach):
            with self.assertRaises(RuntimeError):
                with redirect_stdout(StringIO()):
                    pb_nonfinal.detach()

        self.assertTrue(pb_nonfinal._attached)

        with redirect_stdout(StringIO()):
            pb_nonfinal.detach()

        self.assertNotIn(pb_nonfinal, _active_progress_bars())

        pb_final = log.pb(range(2)).manual()
        self.assertTrue(pb_final._attached)

        with patch.object(progress_module, "detach_progress_bar", new=boom_detach), \
             patch.object(progress_module.sys, "is_finalizing", return_value=True):
            with redirect_stdout(StringIO()):
                pb_final.detach()

        self.assertFalse(pb_final._attached)

        with redirect_stdout(StringIO()):
            original_detach(pb_final)

        self.assertNotIn(pb_final, _active_progress_bars())

    def test_notebook_stack_uses_display_updates(self):
        """Render notebook stacks through IPython display updates when available."""

        pb = log.pb(5).title("NB").manual()
        pb.current_iter_step = 3

        from logbar import logbar as logbar_module

        try:
            import IPython.display as ip_display  # type: ignore
        except ModuleNotFoundError:
            with redirect_stdout(StringIO()):
                pb.close()
            self.skipTest("IPython not available")

        updates = []

        class StubHandle:
            """Minimal IPython display handle used by the notebook test."""

            def update(self, payload, raw=False):
                """Record update payloads and mimic the display handle contract."""

                updates.append(('update', payload, raw))
                return self

            def close(self):
                """Record handle closure for notebook teardown assertions."""

                updates.append(('close', '', None))

        def stub_display(payload, raw=False, display_id=False):
            """Capture the first notebook display payload and return a stub handle."""

            updates.append(('display', payload, raw))
            self.assertTrue(raw)
            self.assertTrue(display_id)
            return StubHandle()

        logbar_module._notebook_display_handle = None

        with patch('logbar.logbar._running_in_notebook_environment', return_value=True), \
             patch('logbar.progress._running_in_notebook_environment', return_value=True), \
             patch.dict('logbar.terminal.os.environ', {}, clear=True), \
             patch.object(ip_display, 'display', side_effect=stub_display):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()
                pb.draw()

        self.assertGreaterEqual(len(updates), 2)
        initial = updates[0][1]
        repeat = updates[-1][1]
        self.assertIn('text/plain', initial)
        self.assertIn('text/html', initial)
        self.assertIn('NB', initial['text/plain'])
        self.assertIn('[3 of 5]', initial['text/html'])
        self.assertIn('<pre', initial['text/html'])
        self.assertIn('<span style=', initial['text/html'])
        self.assertNotIn('\033[', initial['text/plain'])
        self.assertEqual(initial, repeat)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_progress_draw_reuses_backend_state_within_a_frame(self):
        """Avoid repeated backend detection during a single draw call."""

        pb = ProgressBar(range(10))
        pb.manual()
        pb.current_iter_step = 5

        original = progress_module.render_backend_state
        calls = []

        def counting_backend_state(*args, **kwargs):
            """Count backend-state probes while delegating to the real helper."""

            calls.append((args, kwargs))
            return original(*args, **kwargs)

        with patch('logbar.progress.render_backend_state', side_effect=counting_backend_state), \
             patch('logbar.progress.terminal_size', return_value=(48, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()

        self.assertEqual(len(calls), 1)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_log_messages_render_above_progress_bars(self):
        """Keep normal log lines visually above the active progress stack."""

        columns = 100
        pb = log.pb(100).title("PB").manual()
        pb.current_iter_step = 10

        with patch('logbar.progress.terminal_size', return_value=(columns, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()
                log.info("hello world")

        lines = extract_rendered_lines(buffer.getvalue())

        info_indices = [idx for idx, line in enumerate(lines) if 'INFO' in line]
        pb_indices = [idx for idx, line in enumerate(lines) if '| ' in line]

        self.assertTrue(info_indices, "expected a logged INFO line in output")
        self.assertTrue(pb_indices, "expected a progress bar line in output")
        self.assertLess(info_indices[-1], pb_indices[-1])
        self.assertIn('PB', lines[pb_indices[-1]])

        with redirect_stdout(StringIO()):
            pb.close()

    def test_progress_draw_plain_stream_omits_ansi_sequences(self):
        """Suppress ANSI styling when drawing to plain redirected stdout."""

        pb = log.pb(10).title("PB").manual()
        pb.current_iter_step = 5

        with patch.dict('logbar.terminal.os.environ', {}, clear=True), \
             patch('logbar.progress.terminal_size', return_value=(48, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()

        raw = buffer.getvalue()
        self.assertIn('PB', raw)
        self.assertNotIn('\033[', raw)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_progress_draw_plain_stream_strips_ansi_title_and_subtitle(self):
        """Strip ANSI from title and subtitle when rendering to plain streams."""

        pb = log.pb(10).title("\033[31mPB\033[0m").subtitle("\033[32mSUB\033[0m").manual()
        pb.current_iter_step = 5

        with patch.dict('logbar.terminal.os.environ', {}, clear=True), \
             patch('logbar.progress.terminal_size', return_value=(48, 24)):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()

        raw = buffer.getvalue()
        self.assertIn('PB', raw)
        self.assertIn('SUB', raw)
        self.assertNotIn('\033[', raw)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_progress_bar_attach_detach_random_session(self):
        """Stress attach, draw, detach, and logging over a mixed random session."""

        rng = random.Random(1337)
        duration = 10.0
        detach_interval = 1.0
        min_lifetime = 2.0

        start = time.time()
        last_detach = start
        active = []
        attachments = 0
        detachments = 0

        while time.time() - start < duration:
            now = time.time()
            log.info(f"session log {rng.random():.6f}")

            target_count = rng.randint(1, 4)
            while len(active) < target_count:
                total = rng.randint(5, 20)
                pb = log.pb(range(total)).manual()
                pb.current_iter_step = 0
                pb.draw()
                active.append({
                    "pb": pb,
                    "attached_at": time.time(),
                    "total": total,
                })
                attachments += 1

            for entry in list(active):
                pb = entry["pb"]
                if pb.current_iter_step < entry["total"]:
                    pb.current_iter_step += 1
                pb.draw()

            if now - last_detach >= detach_interval and active:
                candidates = [entry for entry in active if now - entry["attached_at"] >= min_lifetime]
                if candidates:
                    victim = rng.choice(candidates)
                    victim["pb"].close()
                    active.remove(victim)
                    detachments += 1
                    last_detach = now

            sys.stdout.flush()
            sleep(0.25)

        for entry in active:
            entry["pb"].close()
        active.clear()

        self.assertGreaterEqual(time.time() - start, duration)
        self.assertGreaterEqual(attachments, 1)
        self.assertGreaterEqual(detachments, 1)
        self.assertEqual(_active_progress_bars(), [])

    def test_spinner_progress_auto_updates(self):
        """Advance spinner animation frames through the shared refresh worker."""

        pb = log.spinner(title="Working", interval=0.1)
        start = time.time()
        last_line = ""
        try:
            while time.time() - start < 5.0:
                sleep(0.1)
                last_line = pb._last_rendered_line or last_line
        finally:
            pb.close()

        phase = pb._phase
        elapsed = time.time() - start
        self.assertGreaterEqual(phase, 5)
        self.assertGreaterEqual(elapsed, 5.0)
        self.assertIn('elapsed', last_line)

    def test_spinner_progress_pulse_advances_frame(self):
        """Let explicit `pulse()` calls advance spinner animation immediately."""

        pb = log.spinner(title="Pulse", interval=10.0, tail_length=2)
        initial_phase = pb._phase
        start = time.time()
        pulses = 0
        last_line = ""
        try:
            while time.time() - start < 5.0:
                pb.pulse()
                pulses += 1
                last_line = pb._last_rendered_line or last_line
                sleep(0.5)
        finally:
            pb.close()

        after_phase = pb._phase
        pulse_duration = time.time() - start
        self.assertGreater(after_phase, initial_phase)
        self.assertGreaterEqual(after_phase - initial_phase, pulses)
        self.assertGreaterEqual(pulse_duration, 5.0)
        self.assertIn('Pulse', last_line)
