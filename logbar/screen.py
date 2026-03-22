# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Region-composed screen driver that delegates terminal I/O to one backend."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from .coordinator import RenderCoordinator
from .drawing import strip_ansi
from .logbar import _RENDER_LOCK
from .screen_backend import AnsiRegionScreenBackend, RegionScreenBackend
from .terminal import RenderBackendState


class RegionScreen:
    """Drive one full-frame surface from a region coordinator plus backend."""

    def __init__(
        self,
        coordinator: RenderCoordinator,
        *,
        backend: Optional[RegionScreenBackend] = None,
        stream: Optional[object] = None,
        size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
        use_alternate_screen: bool = True,
    ) -> None:
        """Bind a coordinator to one output backend."""

        self._coordinator = coordinator
        self._backend = backend or AnsiRegionScreenBackend(
            stream=stream,
            size_provider=size_provider,
            use_alternate_screen=use_alternate_screen,
        )

    @property
    def coordinator(self) -> RenderCoordinator:
        """Return the bound render coordinator."""

        return self._coordinator

    @property
    def backend(self) -> RegionScreenBackend:
        """Return the backend that owns terminal-specific rendering behavior."""

        return self._backend

    def backend_state(self) -> RenderBackendState:
        """Probe the current capabilities and geometry of the bound backend."""

        return self._backend.backend_state()

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
            self._backend.render_lines(lines, backend_state=state)
            return lines

    def close(self) -> None:
        """Restore terminal state and forget the last rendered frame."""

        with _RENDER_LOCK:
            self._backend.close()

    def __enter__(self) -> "RegionScreen":
        """Allow callers to manage screen lifetime with a context manager."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Restore the terminal when leaving a managed screen scope."""

        del exc_type, exc, tb
        self.close()


__all__ = ["RegionScreen"]
