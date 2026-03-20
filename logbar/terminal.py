# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

# adapted from github.com/onsim/shutils

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import sys
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class RenderBackendState:
    columns: int
    lines: int
    is_tty: bool
    notebook: bool
    supports_cursor: bool


def _stream_terminal_size(stream: Optional[object], fallback: tuple[int, int]) -> Optional[tuple[int, int]]:
    target = stream if stream is not None else sys.stdout
    fileno = getattr(target, "fileno", None)
    if not callable(fileno):
        return None

    try:
        size = os.get_terminal_size(fileno())
    except (AttributeError, OSError, ValueError):
        return None

    return (size.columns or fallback[0], size.lines or fallback[1])

def terminal_size(fallback=(80, 24), stream: Optional[object] = None):
    """Get the size of the terminal window.

    For each of the two dimensions, the environment variable, COLUMNS
    and LINES respectively, is checked. If the variable is defined and
    the value is a positive integer, it is used.

    When COLUMNS or LINES is not defined, which is the common case,
    shutil.get_terminal_size is used to determine the current terminal size.

    If the terminal size cannot be successfully queried, either because
    the system doesn't support querying, or because we are not
    connected to a terminal, the value given in fallback parameter
    is used. Fallback defaults to (80, 24) which is the default
    size used by many terminal emulators.

    The value returned is a named tuple of type os.terminal_size.
    """
    # columns, lines are the working values
    try:
        columns = int(os.environ['COLUMNS'])
    except (KeyError, ValueError):
        columns = 0

    try:
        lines = int(os.environ['LINES'])
    except (KeyError, ValueError):
        lines = 0

    # only query if necessary
    if columns <= 0 or lines <= 0:
        size = _stream_terminal_size(stream, fallback)
        if size is None:
            try:
                queried = shutil.get_terminal_size(fallback)
                size = (queried.columns or fallback[0], queried.lines or fallback[1])
            except (OSError, ValueError):
                # shutil.get_terminal_size failed because the runtime does not have an
                # attached terminal. Fall back to the provided default which mirrors
                # the behaviour of shutil.get_terminal_size when a fallback is supplied.
                size = fallback
        if columns <= 0:
            columns = size[0] or fallback[0]
        if lines <= 0:
            lines = size[1] or fallback[1]

    return (columns, lines)


def render_backend_state(
    *,
    stream: Optional[object] = None,
    fallback: tuple[int, int] = (80, 24),
    size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
    notebook: bool = False,
) -> RenderBackendState:
    target = stream if stream is not None else sys.stdout
    provider = size_provider or (lambda: terminal_size(fallback=fallback, stream=target))
    columns, lines = provider()

    is_tty = False
    isatty = getattr(target, "isatty", None)
    if callable(isatty):
        try:
            is_tty = bool(isatty())
        except Exception:
            is_tty = False

    supports_cursor = is_tty or bool(os.environ.get("LOGBAR_FORCE_TERMINAL_CURSOR", "").strip())
    if notebook:
        supports_cursor = False

    return RenderBackendState(
        columns=max(0, int(columns)),
        lines=max(0, int(lines)),
        is_tty=is_tty,
        notebook=notebook,
        supports_cursor=supports_cursor,
    )
