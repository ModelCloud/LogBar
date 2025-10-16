# Copyright 2024-2025 ModelCloud.ai
# Copyright 2024-2025 qubitium@modelcloud.ai
# Contact: qubitium@modelcloud.ai, x.com/qubitium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
from logbar.progress import ProgressBar
from logbar.logbar import _active_progress_bars

log = LogBar.shared(override_logger=True)


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def extract_rendered_lines(buffer: str):
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

    def test_title_fixed_subtitle_dynamic(self):
        pb = log.pb(SAMPLES).title("TITLE:").manual()
        for i in pb:
            pb.subtitle(f"[SUBTITLE: {i}]").draw()
            sleep(0.1)

    def test_title_dynamic_subtitle_fixed(self):
        pb = log.pb(SAMPLES).subtitle("SUBTITLE: FIXED").manual()
        for i in pb:
            pb.title(f"[TITLE: {i}]").draw()
            sleep(0.1)

    def test_title_dynamic_subtitle_dynamic(self):
        pb = log.pb(SAMPLES).manual()
        count = 1
        for i in pb:
            log.info(f"random log: {count}")
            count += 1
            pb.title(f"[TITLE: {i}]").subtitle(f"[SUBTITLE: {i}]").draw()
            sleep(0.1)

    def test_range_manual(self):
        pb = log.pb(range(100)).manual()
        for _ in pb:
            pb.draw()
            sleep(0.1)

    def test_range_auto_int(self):
        pb = log.pb(100)
        for _ in pb:
            sleep(0.1)

    def test_range_auto_dict(self):
        pb = log.pb({"1": 2, "2": 2})

        for _ in pb:
            sleep(0.1)

    def test_range_auto_disable_ui_left_steps(self):
        pb = log.pb(100).set(show_left_steps=False)
        for _ in pb:
            sleep(0.1)

    def test_title(self):
        pb = log.pb(100).title("TITLE: FIXED")
        for _ in pb:
            sleep(0.1)

    def test_title_subtitle(self):
        pb = log.pb(100).title("[TITLE: FIXED]").manual()
        for _ in pb:
            pb.subtitle(f"[SUBTITLE: FIXED]").draw()
            sleep(0.1)

    def test_draw_respects_terminal_width(self):
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

    def test_draw_without_terminal_state(self):
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

    def test_notebook_stack_uses_display_updates(self):
        pb = log.pb(5).title("NB").manual()
        pb.current_iter_step = 3

        from logbar import logbar as logbar_module

        updates = []

        class StubHandle:
            def update(self, payload, raw=False):
                updates.append(('update', payload['text/plain'], raw))
                return self

            def close(self):
                updates.append(('close', '', None))

        def stub_display(payload, raw=False, display_id=False):
            updates.append(('display', payload['text/plain'], raw))
            self.assertTrue(raw)
            self.assertTrue(display_id)
            return StubHandle()

        logbar_module._notebook_display_handle = None

        with patch('logbar.logbar._running_in_notebook_environment', return_value=True), \
             patch('IPython.display.display', side_effect=stub_display):
            buffer = StringIO()
            with redirect_stdout(buffer):
                pb.draw()
                pb.draw()

        self.assertGreaterEqual(len(updates), 2)
        initial = updates[0][1]
        repeat = updates[-1][1]
        self.assertIn('NB', initial)
        self.assertEqual(initial, repeat)

        with redirect_stdout(StringIO()):
            pb.close()

    def test_log_messages_render_above_progress_bars(self):
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

    def test_progress_bar_attach_detach_random_session(self):
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
