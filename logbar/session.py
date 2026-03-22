# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""High-level split-pane session helpers for region-composed rendering."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from .coordinator import RenderCoordinator
from .layout import LayoutNode
from .region import LogRegion
from .region_logger import RegionLogBar
from .screen import RegionScreen


@dataclass
class _SessionPaneState:
    """Track one pane's region plus footer layers owned by the session."""

    region: LogRegion
    static_footer_lines: list[str] = field(default_factory=list)
    progress_bars: list[object] = field(default_factory=list)


class _SessionFooterDelegate:
    """Route logger footer mutations through session-managed pane state."""

    def __init__(self, session: "RegionScreenSession", region_id: str) -> None:
        """Bind one delegate to a session pane identifier."""

        self._session = session
        self._region_id = region_id

    def set_footer_lines(self, lines) -> None:
        """Replace the pane's static footer layer."""

        self._session._set_static_footer_lines(self._region_id, lines)

    def append_footer_line(self, line: str) -> None:
        """Append one line to the pane's static footer layer."""

        self._session._append_static_footer_line(self._region_id, line)

    def clear_footer(self) -> None:
        """Clear the pane's static footer layer."""

        self._session._clear_static_footer(self._region_id)


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
        self._pane_states: dict[str, _SessionPaneState] = {}
        self._dirty_progress_bars: set[object] = set()
        self._last_render_size: Optional[tuple[int, int]] = None

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

        self._ensure_pane_state(region_id)
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
            footer_delegate=_SessionFooterDelegate(self, str(region_id).strip()),
        )

    def pb(
        self,
        iterable,
        *,
        region_id: Optional[str] = None,
        output_interval: Optional[int] = None,
    ):
        """Create and attach a pane-local determinate progress bar."""

        from .region_progress import RegionProgressBar

        target_region_id = self._normalize_region_id(region_id)
        bar = RegionProgressBar(
            iterable,
            session=self,
            region_id=target_region_id,
            output_interval=output_interval,
        )
        return bar.attach()

    def spinner(
        self,
        *,
        region_id: Optional[str] = None,
        title: str = "",
        interval: float = 0.5,
        tail_length: int = 4,
    ):
        """Create and attach a pane-local rolling spinner."""

        from .region_progress import RegionRollingProgressBar

        target_region_id = self._normalize_region_id(region_id)
        bar = RegionRollingProgressBar(
            session=self,
            region_id=target_region_id,
            interval=interval,
            tail_length=tail_length,
        ).attach()
        if title:
            bar.title(title)
        return bar

    def refresh_progress(self, *, force: bool = False) -> list[str]:
        """Advance time-based pane progress bars once and repaint the session."""

        state = self._screen.backend_state()
        now = time.monotonic()
        size_changed = self._last_render_size != (state.columns, state.lines)
        changed = size_changed or force

        for pane in self._pane_states.values():
            for pb in list(pane.progress_bars):
                tick = getattr(pb, "_tick_background_refresh", None)
                if callable(tick) and tick(now):
                    changed = True

        if changed:
            return self.render(backend_state=state, force_progress_refresh=True)

        return self._screen.compose_lines(backend_state=state)

    def render(
        self,
        *,
        backend_state=None,
        force_progress_refresh: bool = False,
    ) -> list[str]:
        """Render the current layout frame through the bound screen backend."""

        state = backend_state or self._screen.backend_state()
        size_changed = self._last_render_size != (state.columns, state.lines)
        self._sync_all_pane_footers(
            backend_state=state,
            force=force_progress_refresh or size_changed,
            allow_repeat=True,
        )
        lines = self._screen.render(backend_state=state)
        self._last_render_size = (state.columns, state.lines)
        return lines

    def close(self) -> None:
        """Close the screen backend and restore the terminal state."""

        self._screen.close()
        self._last_render_size = None

    def _render_logger_change(self, logger: RegionLogBar) -> None:
        """Repaint the session after one logger mutates its region."""

        del logger
        self.render()

    def _normalize_region_id(self, region_id: Optional[str]) -> str:
        """Normalize one caller-supplied region identifier."""

        normalized = str(region_id or self._coordinator.root_region_id).strip()
        return normalized or self._coordinator.root_region_id

    def _ensure_pane_state(self, region_id: Optional[str]) -> _SessionPaneState:
        """Create or return the pane state for one region identifier."""

        normalized = self._normalize_region_id(region_id)
        pane = self._pane_states.get(normalized)
        region = self._coordinator.region(normalized)

        if region is None:
            region = self._coordinator.register_region(normalized, LogRegion())
        elif not isinstance(region, LogRegion):
            raise TypeError(f"Registered region {normalized!r} is not a LogRegion.")

        if pane is None or pane.region is not region:
            pane = _SessionPaneState(region=region)
            self._pane_states[normalized] = pane

        return pane

    def _set_static_footer_lines(self, region_id: str, lines) -> None:
        """Replace the pane-owned static footer layer and resync the region."""

        pane = self._ensure_pane_state(region_id)
        pane.static_footer_lines = [str(line) for line in lines]
        self._sync_pane_footer(region_id)

    def _append_static_footer_line(self, region_id: str, line: str) -> None:
        """Append one line to the pane-owned static footer layer."""

        pane = self._ensure_pane_state(region_id)
        pane.static_footer_lines.append(str(line))
        self._sync_pane_footer(region_id)

    def _clear_static_footer(self, region_id: str) -> None:
        """Clear the pane-owned static footer layer."""

        pane = self._ensure_pane_state(region_id)
        pane.static_footer_lines = []
        self._sync_pane_footer(region_id)

    def _progress_width(self, region_id: str, backend_state) -> int:
        """Resolve the current viewport width for one pane's progress footer."""

        viewports = self._coordinator.resolve_viewports(
            columns=backend_state.columns,
            lines=backend_state.lines,
        )
        viewport = viewports.get(region_id)
        if viewport is None:
            return backend_state.columns
        return viewport.width

    def _sync_pane_footer(
        self,
        region_id: str,
        *,
        backend_state=None,
        force: bool = False,
        allow_repeat: bool = True,
        precomputed: Optional[dict] = None,
    ) -> None:
        """Recompose one pane footer from static footer lines and progress rows."""

        pane = self._ensure_pane_state(region_id)
        if not pane.progress_bars and not pane.static_footer_lines:
            pane.region.clear_footer()
            return

        state = backend_state or self._screen.backend_state()
        width = self._progress_width(region_id, state)
        progress_lines: list[str] = []
        active_bars: list[object] = []

        for pb in pane.progress_bars:
            if getattr(pb, "closed", False):
                continue

            active_bars.append(pb)
            bar_force = force or pb in self._dirty_progress_bars
            rendered = precomputed.get(pb) if precomputed is not None else None
            if rendered is None:
                rendered = pb._resolve_rendered_line(
                    width,
                    force=bar_force,
                    allow_repeat=allow_repeat,
                    backend_state=state,
                    style_enabled=state.supports_styling,
                )
                if rendered is None:
                    rendered = pb._last_rendered_line or ""

            progress_lines.append(rendered or "")
            self._dirty_progress_bars.discard(pb)

        pane.progress_bars = active_bars
        pane.region.set_footer_lines(pane.static_footer_lines + progress_lines)

    def _sync_all_pane_footers(
        self,
        *,
        backend_state,
        force: bool = False,
        allow_repeat: bool = True,
    ) -> None:
        """Recompose every pane footer that currently has progress rows."""

        for region_id, pane in self._pane_states.items():
            if pane.progress_bars:
                self._sync_pane_footer(
                    region_id,
                    backend_state=backend_state,
                    force=force,
                    allow_repeat=allow_repeat,
                )

    def _attach_progress_bar(self, region_id: str, pb: object) -> None:
        """Register one pane-local progress bar in the target region."""

        pane = self._ensure_pane_state(region_id)
        if pb not in pane.progress_bars:
            pane.progress_bars.append(pb)
        self._dirty_progress_bars.add(pb)
        self._sync_pane_footer(region_id, force=True, allow_repeat=True)
        if self._auto_render:
            self.render(force_progress_refresh=True)

    def _detach_progress_bar(self, region_id: str, pb: object) -> None:
        """Remove one pane-local progress bar and restore the footer layer."""

        pane = self._ensure_pane_state(region_id)
        if pb in pane.progress_bars:
            pane.progress_bars.remove(pb)
        self._dirty_progress_bars.discard(pb)
        self._sync_pane_footer(region_id, force=True, allow_repeat=True)
        if self._auto_render:
            self.render(force_progress_refresh=True)

    def _mark_progress_bar_dirty(self, region_id: str, pb: object) -> None:
        """React to one attached pane-local progress bar becoming dirty."""

        self._dirty_progress_bars.add(pb)
        if self._auto_render:
            self._sync_pane_footer(region_id, force=True, allow_repeat=True)
            self.render(force_progress_refresh=True)

    def _draw_progress_bar(self, region_id: str, pb: object, *, force: bool = False) -> None:
        """Resolve one pane-local progress bar and optionally repaint the screen."""

        state = self._screen.backend_state()
        size_changed = self._last_render_size != (state.columns, state.lines)
        width = self._progress_width(region_id, state)
        rendered = pb._resolve_rendered_line(
            width,
            force=force or size_changed,
            allow_repeat=True,
            backend_state=state,
            style_enabled=state.supports_styling,
        )

        if rendered is None and not size_changed:
            return

        precomputed = {pb: rendered} if rendered is not None else None
        self._sync_pane_footer(
            region_id,
            backend_state=state,
            force=force or size_changed,
            allow_repeat=True,
            precomputed=precomputed,
        )
        self._dirty_progress_bars.discard(pb)
        if self._auto_render:
            self.render(backend_state=state, force_progress_refresh=size_changed)

    def __enter__(self) -> "RegionScreenSession":
        """Allow callers to manage the session lifetime with a context manager."""

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Restore terminal state when leaving the session scope."""

        del exc_type, exc, tb
        self.close()


__all__ = ["RegionScreenSession"]
