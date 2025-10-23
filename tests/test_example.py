# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import time
from logbar import LogBar

log = LogBar.shared()

pb_fetch = log.pb(range(80)).title("Fetch").manual()
pb_train = log.pb(range(120)).title("Train").manual()

for _ in pb_fetch:
    pb_fetch.draw()
    time.sleep(0.01)

for _ in pb_train:
    pb_train.draw()
    time.sleep(0.01)

pb_train.close()
pb_fetch.close()
