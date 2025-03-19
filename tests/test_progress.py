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
from time import sleep

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
