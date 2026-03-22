# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Experimental ANSI screen backend for region-composed layouts."""

from __future__ import annotations

import sys
from typing import Callable, Optional, Sequence, Tuple

from .buffer import get_buffered_stdout
from .coordinator import RenderCoordinator
from .drawing import strip_ansi
from .logbar import _RENDER_LOCK
from .terminal import RenderBackendState, render_backend_state


class RegionScreen:
    """Drive one full-frame terminal surface from a region coordinator."""

    def __init__(
        self,
        coordinator: RenderCoordinator,
        *,
        stream: Optional[object] = None,
        size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
        use_alternate_screen: bool = True,
    ) -> None:
        """Bind a coordinator to one output stream and size probe."""

        self._coordinator = coordinator
        self._base_stream = stream if stream is not None else sys.stdout
        self._stream = get_buffered_stdout(self._base_stream)
        self._size_provider = size_provider
        self._use_alternate_screen = bool(use_alternate_screen)
        self._entered_alternate_screen = False
        self._cursor_hidden = False
        self._last_rendered_lines: list[str] = []
        self._last_rendered_size: Optional[tuple[int, int]] = None

    @property
    def coordinator(self) -> RenderCoordinator:
        """Return the bound render coordinator."""

        return self._coordinator

    def backend_state(self) -> RenderBackendState:
        """Probe the current capabilities and geometry of the bound stream."""

        return render_backend_state(
            stream=self._stream,
            size_provider=self._size_provider,
        )

    def compose_lines(self, *, backend_state: Optional[RenderBackendState] = None) -> list[str]:
        """Resolve the coordinator into fully composed terminal rows."""

        state = backend_state or self.backend_state()
        rows = self._coordinator.compose_layout_lines(
            columns=state.columns,
            lines=state.lines,
            style_enabled=state.supports_styling,
        )
        if state.supports_ansi:
            return rows
        return [strip_ansi(row) for row in rows]

    def render(self, *, backend_state: Optional[RenderBackendState] = None) -> list[str]:
        """Compose and paint the current layout frame onto the target stream."""

        with _RENDER_LOCK:
            state = backend_state or self.backend_state()
            lines = self.compose_lines(backend_state=state)

            if not state.supports_cursor:
                payload = "\n".join(lines)
                if payload:
                    self._write(payload)
                    self._write("\n")
                    self._flush()
                self._last_rendered_lines = list(lines)
                self._last_rendered_size = (state.columns, state.lines)
                return lines

            sequences: list[str] = []
            size_changed = self._last_rendered_size != (state.columns, state.lines)

            if self._use_alternate_screen and not self._entered_alternate_screen:
                sequences.append("\033[?1049h")
                self._entered_alternate_screen = True
                size_changed = True

            if not self._cursor_hidden:
                sequences.append("\033[?25l")
                self._cursor_hidden = True

            if size_changed or len(self._last_rendered_lines) != len(lines):
                sequences.append("\033[2J")
                row_indexes = list(range(len(lines)))
            else:
                row_indexes = [
                    index
                    for index, (old_line, new_line) in enumerate(zip(self._last_rendered_lines, lines))
                    if old_line != new_line
                ]

            for row_index in row_indexes:
                sequences.append(f"\033[{row_index + 1};1H")
                sequences.append("\033[2K")
                sequences.append(lines[row_index])

            if lines:
                sequences.append("\033[1;1H")

            if sequences:
                self._write("".join(sequences))
                self._flush()

            self._last_rendered_lines = list(lines)
            self._last_rendered_size = (state.columns, state.lines)
            return lines

    def close(self) -> None:
        """Restore terminal state and forget the last rendered frame."""

        with _RENDER_LOCK:
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

    def __enter__(self) -> "RegionScreen":
        """Allow callers to manage screen lifetime with a context manager."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Restore the terminal when leaving a managed screen scope."""

        del exc_type, exc, tb
        self.close()

    def _write(self, data: str) -> int:
        """Write one raw payload to the bound output stream."""

        return self._stream.write(data)

    def _flush(self) -> None:
        """Flush the bound output stream when supported."""

        flush = getattr(self._stream, "flush", None)
        if callable(flush):
            flush()


__all__ = ["RegionScreen"]
