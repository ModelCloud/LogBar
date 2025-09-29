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

import unittest
from contextlib import redirect_stdout
from io import StringIO
from time import sleep
from unittest.mock import patch

from logbar import LogBar

log = LogBar.shared(override_logger=True)

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
            sleep(0.2)

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

        output = buffer.getvalue()
        self.assertTrue(output.startswith('\r'))
        rendered_line = output.lstrip('\r')

        self.assertEqual(len(rendered_line), columns)

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
