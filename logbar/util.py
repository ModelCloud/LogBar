# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

from typing import Iterable, Optional, Union

def auto_iterable(input) -> Optional[Iterable]:
    """Expand convenience inputs into iterables accepted by progress helpers."""

    if isinstance(input, Iterable):
        return input

    if isinstance(input, int):
        return range(input)

    # Preserve the library's historical convenience behaviour for mapping-like
    # inputs where callers usually expect key/value pairs rather than keys only.
    if isinstance(input, (dict, set)):
        return input.items()

    return None
