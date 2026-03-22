# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""High-level split-pane session helpers for region-composed rendering."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from .coordinator import RenderCoordinator
from .layout import LayoutNode
from .region_logger import RegionLogBar
from .screen import RegionScreen


class RegionScreenSession:
    """Bind a coordinator, screen backend, and region loggers into one session."""

    def __init__(
        self,
        *,
        coordinator: Optional[RenderCoordinator] = None,
        layout_root: Optional[LayoutNode] = None,
        stream: Optional[object] = None,
        size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
        use_alternate_screen: bool = True,
        auto_render: bool = True,
    ) -> None:
        """Create one split-pane session with optional auto repaint."""

        self._coordinator = coordinator if coordinator is not None else RenderCoordinator()
        if layout_root is not None:
            self._coordinator.set_layout(layout_root)

        self._screen = RegionScreen(
            self._coordinator,
            stream=stream,
            size_provider=size_provider,
            use_alternate_screen=use_alternate_screen,
        )
        self._auto_render = bool(auto_render)

    @property
    def coordinator(self) -> RenderCoordinator:
        """Return the coordinator that owns the session layout and regions."""

        return self._coordinator

    @property
    def screen(self) -> RegionScreen:
        """Return the bound screen backend."""

        return self._screen

    @property
    def auto_render(self) -> bool:
        """Return whether region mutations trigger an immediate repaint."""

        return self._auto_render

    def set_layout(self, layout_root: Optional[LayoutNode] = None) -> LayoutNode:
        """Replace the active layout tree and optionally repaint."""

        layout = self._coordinator.set_layout(layout_root)
        if self._auto_render:
            self.render()
        return layout

    def create_logger(
        self,
        region_id: str,
        *,
        name: Optional[str] = None,
        supports_ansi: Optional[bool] = None,
        render_on_change: Optional[bool] = None,
    ) -> RegionLogBar:
        """Create one region-bound logger and optionally repaint after mutations."""

        should_render = self._auto_render if render_on_change is None else bool(render_on_change)
        callback = self._render_logger_change if should_render else None

        resolved_supports_ansi = supports_ansi
        if resolved_supports_ansi is None:
            resolved_supports_ansi = self._screen.backend_state().supports_ansi

        return self._coordinator.create_region_logger(
            region_id,
            name=name,
            supports_ansi=bool(resolved_supports_ansi),
            on_change=callback,
        )

    def render(self) -> list[str]:
        """Render the current layout frame through the bound screen backend."""

        return self._screen.render()

    def close(self) -> None:
        """Close the screen backend and restore the terminal state."""

        self._screen.close()

    def _render_logger_change(self, logger: RegionLogBar) -> None:
        """Repaint the session after one logger mutates its region."""

        del logger
        self.render()

    def __enter__(self) -> "RegionScreenSession":
        """Allow callers to manage the session lifetime with a context manager."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Restore terminal state when leaving the session scope."""

        del exc_type, exc, tb
        self.close()


__all__ = ["RegionScreenSession"]
