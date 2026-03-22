# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Coordinator primitives for region-aware LogBar renderers."""

from __future__ import annotations

from typing import Callable, Optional, Sequence


StateChangeCallback = Callable[[str, object], None]


class RenderCoordinatorState:
    """Mutable state container for one render coordinator instance."""

    def __init__(self, on_change: Optional[StateChangeCallback] = None) -> None:
        """Initialize the coordinator state with the current single-stack fields."""

        object.__setattr__(self, "_on_change", on_change)
        object.__setattr__(self, "_attached_progress_bars", [])
        object.__setattr__(self, "_dirty_progress_bars", set())
        object.__setattr__(self, "_last_drawn_progress_count", 0)
        object.__setattr__(self, "_last_rendered_terminal_size", None)
        object.__setattr__(self, "_last_rendered_progress_lines", [])
        object.__setattr__(self, "_cursor_positioned_above_stack", False)
        object.__setattr__(self, "_cursor_positioned_on_stack_top", False)
        object.__setattr__(self, "_stack_redraw_invalidated", False)
        object.__setattr__(self, "_deferred_log_records", [])
        object.__setattr__(self, "_cursor_hidden", False)
        object.__setattr__(self, "_refresh_thread", None)
        object.__setattr__(self, "_last_active_draw", 0.0)

    def __setattr__(self, name: str, value: object) -> None:
        """Store a state field and notify the compatibility layer on rebinding."""

        object.__setattr__(self, name, value)
        if name == "_on_change":
            return

        callback = getattr(self, "_on_change", None)
        if callable(callback):
            callback(name, value)

    def field_names(self) -> Sequence[str]:
        """Return the mutable state field names tracked by the coordinator."""

        return (
            "_attached_progress_bars",
            "_dirty_progress_bars",
            "_last_drawn_progress_count",
            "_last_rendered_terminal_size",
            "_last_rendered_progress_lines",
            "_cursor_positioned_above_stack",
            "_cursor_positioned_on_stack_top",
            "_stack_redraw_invalidated",
            "_deferred_log_records",
            "_cursor_hidden",
            "_refresh_thread",
            "_last_active_draw",
        )


class RenderCoordinator:
    """Own the mutable render state for one LogBar terminal surface."""

    def __init__(self, on_state_change: Optional[StateChangeCallback] = None) -> None:
        """Create a coordinator around a fresh mutable state object."""

        self.state = RenderCoordinatorState(on_change=on_state_change)

    def attach_progress_bar(self, pb: object) -> None:
        """Register one progress renderable with the coordinator."""

        if pb not in self.state._attached_progress_bars:
            self.state._attached_progress_bars.append(pb)
        self.state._dirty_progress_bars.add(pb)

    def detach_progress_bar(self, pb: object) -> None:
        """Remove one progress renderable from the coordinator."""

        if pb in self.state._attached_progress_bars:
            self.state._attached_progress_bars.remove(pb)
        self.state._dirty_progress_bars.discard(pb)

    def mark_progress_bar_dirty(self, pb: object) -> None:
        """Flag one attached renderable for a future redraw."""

        if pb in self.state._attached_progress_bars:
            self.state._dirty_progress_bars.add(pb)

    def active_progress_bars(self) -> list[object]:
        """Return a stable snapshot of the attached progress renderables."""

        return list(self.state._attached_progress_bars)


__all__ = ["RenderCoordinator", "RenderCoordinatorState"]
