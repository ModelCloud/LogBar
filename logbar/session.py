# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""High-level split-pane session helpers for region-composed rendering."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from .coordinator import RenderCoordinator
from .layout import LeafNode, LayoutNode, SplitNode, columns as layout_columns, rows as layout_rows
from .logbar import _RENDER_LOCK
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

    @classmethod
    def from_layout(cls, layout_root: LayoutNode, **kwargs) -> "RegionScreenSession":
        """Create one session from a prebuilt public layout tree."""

        return cls(layout_root=layout_root, **kwargs)

    @classmethod
    def columns(
        cls,
        *children,
        weights=None,
        gutter: int = 1,
        divider: Optional[str] = None,
        **kwargs,
    ) -> "RegionScreenSession":
        """Create one session whose root layout is a left-to-right split."""

        return cls(
            layout_root=layout_columns(*children, weights=weights, gutter=gutter, divider=divider),
            **kwargs,
        )

    @classmethod
    def rows(
        cls,
        *children,
        weights=None,
        gutter: int = 1,
        divider: Optional[str] = None,
        **kwargs,
    ) -> "RegionScreenSession":
        """Create one session whose root layout is a top-to-bottom split."""

        return cls(
            layout_root=layout_rows(*children, weights=weights, gutter=gutter, divider=divider),
            **kwargs,
        )

    def __init__(
        self,
        *,
        coordinator: Optional[RenderCoordinator] = None,
        layout_root: Optional[LayoutNode] = None,
        stream: Optional[object] = None,
        size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
        use_alternate_screen: bool = True,
        auto_render: bool = True,
        background_refresh: Optional[bool] = None,
        refresh_interval_seconds: float = 0.1,
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
        self._background_refresh_enabled = (
            self._auto_render if background_refresh is None else (bool(background_refresh) and self._auto_render)
        )
        self._refresh_interval_seconds = max(0.01, float(refresh_interval_seconds))
        self._pane_states: dict[str, _SessionPaneState] = {}
        self._dirty_progress_bars: set[object] = set()
        self._last_render_size: Optional[tuple[int, int]] = None
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_thread_lock = threading.Lock()
        self._refresh_stop_event = threading.Event()
        self._register_layout_regions(self._coordinator.layout_root)

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

    @property
    def background_refresh_enabled(self) -> bool:
        """Return whether this session may auto-refresh pane progress in the background."""

        return self._background_refresh_enabled

    def set_layout(self, layout_root: Optional[LayoutNode] = None) -> LayoutNode:
        """Replace the active layout tree and optionally repaint."""

        layout = self._coordinator.set_layout(layout_root)
        self._register_layout_regions(layout)
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

        with _RENDER_LOCK:
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

        with _RENDER_LOCK:
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

        self.stop_background_refresh()
        self._screen.close()
        self._last_render_size = None

    def start_background_refresh(self) -> Optional[threading.Thread]:
        """Start the session-owned progress refresher when enabled and needed."""

        if not self._background_refresh_enabled or not self._has_active_progress_bars():
            return None

        with self._refresh_thread_lock:
            if self._refresh_thread is not None and self._refresh_thread.is_alive():
                return self._refresh_thread

            self._refresh_stop_event.clear()
            thread = threading.Thread(
                target=self._background_refresh_worker,
                name="logbar-region-session-refresh",
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()
            return thread

    def stop_background_refresh(self) -> None:
        """Stop the session-owned background refresher if it is running."""

        with self._refresh_thread_lock:
            thread = self._refresh_thread
            if thread is None:
                return
            self._refresh_stop_event.set()

        if thread is not threading.current_thread():
            thread.join(timeout=max(0.1, self._refresh_interval_seconds * 5))

        with self._refresh_thread_lock:
            if self._refresh_thread is thread and not thread.is_alive():
                self._refresh_thread = None

    def _render_logger_change(self, logger: RegionLogBar) -> None:
        """Repaint the session after one logger mutates its region."""

        del logger
        self.render()

    def _normalize_region_id(self, region_id: Optional[str]) -> str:
        """Normalize one caller-supplied region identifier."""

        normalized = str(region_id or self._coordinator.root_region_id).strip()
        return normalized or self._coordinator.root_region_id

    def _register_layout_regions(self, layout_root: LayoutNode) -> None:
        """Ensure every layout leaf has a backing pane region registered."""

        for region_id in self._layout_region_ids(layout_root):
            self._ensure_pane_state(region_id)

    def _layout_region_ids(self, node: LayoutNode) -> list[str]:
        """Collect all region ids from one public layout tree."""

        if isinstance(node, LeafNode):
            return [node.region_id]
        if isinstance(node, SplitNode):
            region_ids: list[str] = []
            for child in node.children:
                region_ids.extend(self._layout_region_ids(child))
            return region_ids
        raise TypeError(f"Unsupported layout node type: {type(node)!r}")

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

    def _has_active_progress_bars(self) -> bool:
        """Return whether any pane currently owns attached progress bars."""

        return any(pane.progress_bars for pane in self._pane_states.values())

    def _should_refresh_in_background(self, backend_state) -> bool:
        """Return whether the session refresher should tick under one backend."""

        if not self._has_active_progress_bars():
            return False

        if backend_state.supports_cursor or backend_state.notebook:
            return True

        for pane in self._pane_states.values():
            for pb in pane.progress_bars:
                if callable(getattr(pb, "_tick_background_refresh", None)):
                    return True

        return False

    def _background_refresh_worker(self) -> None:
        """Advance pane-local time-based renderables until the session stops."""

        while not self._refresh_stop_event.wait(self._refresh_interval_seconds):
            if not self._has_active_progress_bars():
                continue

            try:
                state = self._screen.backend_state()
            except Exception:
                continue

            if not self._should_refresh_in_background(state):
                continue

            try:
                self.refresh_progress()
            except Exception:
                continue

    def _attach_progress_bar(self, region_id: str, pb: object) -> None:
        """Register one pane-local progress bar in the target region."""

        pane = self._ensure_pane_state(region_id)
        if pb not in pane.progress_bars:
            pane.progress_bars.append(pb)
        self._dirty_progress_bars.add(pb)
        self._sync_pane_footer(region_id, force=True, allow_repeat=True)
        if self._auto_render:
            self.render(force_progress_refresh=True)
        self.start_background_refresh()

    def _detach_progress_bar(self, region_id: str, pb: object) -> None:
        """Remove one pane-local progress bar and restore the footer layer."""

        pane = self._ensure_pane_state(region_id)
        if pb in pane.progress_bars:
            pane.progress_bars.remove(pb)
        self._dirty_progress_bars.discard(pb)
        self._sync_pane_footer(region_id, force=True, allow_repeat=True)
        if self._auto_render:
            self.render(force_progress_refresh=True)
        if not self._has_active_progress_bars():
            self.stop_background_refresh()

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
