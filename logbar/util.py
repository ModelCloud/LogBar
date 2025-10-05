# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

from typing import Iterable, Optional, Union

# simplify user usage so instead of this: pb(range(10))
# they use: pb(10)
def auto_iterable(input) -> Optional[Iterable]:
    if isinstance(input, Iterable):
        return input

    if isinstance(input, int):
        return range(input)

    # when you iterate dict/sets, 99% of the time you want to call items()
    # and for loop k,v
    if isinstance(input, (dict, set)):
        return input.items()

    return None

