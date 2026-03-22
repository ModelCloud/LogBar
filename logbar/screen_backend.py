# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Backend interfaces and ANSI implementations for region-composed screens."""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional, Protocol, Sequence, Tuple

from .buffer import get_buffered_stdout
from .terminal import RenderBackendState, render_backend_state


class RegionScreenBackend(Protocol):
    """Backend contract for region-composed screen renderers."""

    def backend_state(self) -> RenderBackendState:
        """Probe the current capabilities and geometry of the target backend."""

    def render_lines(
        self,
        lines: Sequence[str],
        *,
        backend_state: Optional[RenderBackendState] = None,
    ) -> None:
        """Paint one full composed frame represented as terminal rows."""

    def close(self) -> None:
        """Restore backend state and release any fullscreen resources."""


class AnsiRegionScreenBackend:
    """ANSI/stdout backend for region-composed screen rendering."""

    def __init__(
        self,
        *,
        stream: Optional[object] = None,
        size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
        use_alternate_screen: bool = True,
    ) -> None:
        """Bind the backend to one stream and size probe."""

        self._base_stream = stream if stream is not None else sys.stdout
        self._stream = get_buffered_stdout(self._base_stream)
        self._size_provider = size_provider
        self._use_alternate_screen = bool(use_alternate_screen)
        self._entered_alternate_screen = False
        self._cursor_hidden = False
        self._last_rendered_lines: list[str] = []
        self._last_rendered_size: Optional[tuple[int, int]] = None
        self._lock = threading.RLock()

    def backend_state(self) -> RenderBackendState:
        """Probe the current capabilities and geometry of the bound stream."""

        with self._lock:
            return render_backend_state(
                stream=self._stream,
                size_provider=self._size_provider,
            )

    def render_lines(
        self,
        lines: Sequence[str],
        *,
        backend_state: Optional[RenderBackendState] = None,
    ) -> None:
        """Paint one frame of composed lines onto the ANSI terminal backend."""

        with self._lock:
            state = backend_state or self.backend_state()
            normalized_lines = [str(line) for line in lines]

            if not state.supports_cursor:
                payload = "\n".join(normalized_lines)
                if payload:
                    self._write(payload)
                    self._write("\n")
                    self._flush()
                self._last_rendered_lines = list(normalized_lines)
                self._last_rendered_size = (state.columns, state.lines)
                return

            sequences: list[str] = []
            size_changed = self._last_rendered_size != (state.columns, state.lines)

            if self._use_alternate_screen and not self._entered_alternate_screen:
                sequences.append("\033[?1049h")
                self._entered_alternate_screen = True
                size_changed = True

            if not self._cursor_hidden:
                sequences.append("\033[?25l")
                self._cursor_hidden = True

            if size_changed or len(self._last_rendered_lines) != len(normalized_lines):
                sequences.append("\033[2J")
                row_indexes = list(range(len(normalized_lines)))
            else:
                row_indexes = [
                    index
                    for index, (old_line, new_line) in enumerate(zip(self._last_rendered_lines, normalized_lines))
                    if old_line != new_line
                ]

            for row_index in row_indexes:
                sequences.append(f"\033[{row_index + 1};1H")
                sequences.append("\033[2K")
                sequences.append(normalized_lines[row_index])

            if normalized_lines:
                sequences.append("\033[1;1H")

            if sequences:
                self._write("".join(sequences))
                self._flush()

            self._last_rendered_lines = list(normalized_lines)
            self._last_rendered_size = (state.columns, state.lines)

    def close(self) -> None:
        """Restore terminal state and forget the last rendered frame."""

        with self._lock:
            sequences: list[str] = []
            if self._cursor_hidden:
                sequences.append("\033[?25h")
                self._cursor_hidden = False
            if self._entered_alternate_screen:
                sequences.append("\033[?1049l")
                self._entered_alternate_screen = False
            if sequences:
                self._write("".join(sequences))
                self._flush()
            self._last_rendered_lines = []
            self._last_rendered_size = None

    def _write(self, data: str) -> int:
        """Write one raw payload to the bound output stream."""

        return self._stream.write(data)

    def _flush(self) -> None:
        """Flush the bound output stream when supported."""

        flush = getattr(self._stream, "flush", None)
        if callable(flush):
            flush()


__all__ = ["AnsiRegionScreenBackend", "RegionScreenBackend"]
