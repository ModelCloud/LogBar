# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Coordinator primitives for region-aware LogBar renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterator, Optional, Sequence

from .drawing import ANSI_RESET, strip_ansi, truncate_ansi, visible_length
from .frame import CellBuffer
from .layout import DividerAssignment, LeafNode, LayoutNode, ResolvedLayout, Viewport
from .region import RenderContext, clip_rendered_lines, line_region_start_row


StateChangeCallback = Callable[[str, object], None]
DEFAULT_ROOT_REGION_ID = "root"


@dataclass(frozen=True)
class ResolvedRegion:
    """Bind one registered region object to its resolved terminal rectangle."""

    region_id: str
    region: object
    viewport: Viewport


@dataclass(frozen=True)
class ResolvedCoordinatorLayout:
    """Bind one resolved layout tree to registered region objects."""

    root_viewport: Viewport
    layout: ResolvedLayout
    regions: list[ResolvedRegion]


@dataclass(frozen=True)
class RowSegment:
    """Describe one already-clipped line segment placed on a root row."""

    x: int
    width: int
    text: str


@dataclass(frozen=True)
class PositionedRegion:
    """Carry one resolved region with its render context and root-local offset."""

    resolved: ResolvedRegion
    context: RenderContext
    local_x: int
    local_y: int


@dataclass(frozen=True)
class ClippedDivider:
    """Describe one root-clipped divider rectangle in root-local coordinates."""

    local_x: int
    local_y: int
    width: int
    height: int
    fill: str


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

    def __init__(
        self,
        on_state_change: Optional[StateChangeCallback] = None,
        *,
        root_region_id: str = DEFAULT_ROOT_REGION_ID,
    ) -> None:
        """Create a coordinator around a fresh mutable state object."""

        normalized_root = str(root_region_id).strip() or DEFAULT_ROOT_REGION_ID
        self._root_region_id = normalized_root
        self._layout_root: LayoutNode = LeafNode(normalized_root)
        self._regions: Dict[str, object] = {}
        self.state = RenderCoordinatorState(on_change=on_state_change)

    @property
    def root_region_id(self) -> str:
        """Return the identifier used by the default single-region layout."""

        return self._root_region_id

    @property
    def layout_root(self) -> LayoutNode:
        """Return the current layout tree root."""

        return self._layout_root

    def root_viewport(self, *, columns: int, lines: int) -> Viewport:
        """Build the coordinator's root terminal rectangle from backend dimensions."""

        return Viewport(0, 0, max(0, int(columns)), max(0, int(lines)))

    def set_layout(self, layout_root: Optional[LayoutNode] = None) -> LayoutNode:
        """Install a layout tree or restore the default single-root leaf."""

        self._layout_root = layout_root if layout_root is not None else LeafNode(self._root_region_id)
        return self._layout_root

    def resolve_viewports(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> Dict[str, Viewport]:
        """Resolve the active layout tree into concrete leaf rectangles."""

        return dict(self._resolve_layout(columns=columns, lines=lines, viewport=viewport).viewports)

    def register_region(self, region_id: str, region: object) -> object:
        """Associate one region object with a layout leaf identifier."""

        normalized = str(region_id).strip()
        if not normalized:
            raise ValueError("region_id must not be empty.")
        self._regions[normalized] = region
        return region

    def unregister_region(self, region_id: str) -> Optional[object]:
        """Remove one previously registered region object."""

        normalized = str(region_id).strip()
        if not normalized:
            return None
        return self._regions.pop(normalized, None)

    def region(self, region_id: str) -> Optional[object]:
        """Return the registered object for one region identifier."""

        return self._regions.get(str(region_id).strip())

    def registered_regions(self) -> Dict[str, object]:
        """Return a defensive copy of the region registry."""

        return dict(self._regions)

    def create_region_logger(
        self,
        region_id: str,
        *,
        name: Optional[str] = None,
        supports_ansi: bool = True,
        on_change: Optional[Callable[[object], None]] = None,
        footer_delegate: Optional[object] = None,
    ) -> "RegionLogBar":
        """Return a region-bound logger backed by one registered LogRegion."""

        from .region import LogRegion
        from .region_logger import RegionLogBar

        normalized = str(region_id).strip()
        if not normalized:
            raise ValueError("region_id must not be empty.")

        region = self.region(normalized)
        if region is None:
            region = self.register_region(normalized, LogRegion())
        elif not isinstance(region, LogRegion):
            raise TypeError(f"Registered region {normalized!r} is not a LogRegion.")

        return RegionLogBar(
            name or normalized,
            region=region,
            supports_ansi=supports_ansi,
            on_change=on_change,
            footer_delegate=footer_delegate,
        )

    def resolve_registered_regions(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> list[ResolvedRegion]:
        """Resolve the layout tree and bind each leaf to a registered region object."""

        return list(
            self._resolve_registered_layout(columns=columns, lines=lines, viewport=viewport).regions
        )

    def compose_frame(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
        style_enabled: bool = True,
    ) -> CellBuffer:
        """Render all registered layout leaves into one composed root frame."""

        resolved_layout = self._resolve_registered_layout(columns=columns, lines=lines, viewport=viewport)
        frame = CellBuffer(
            resolved_layout.root_viewport.width,
            resolved_layout.root_viewport.height,
        )
        for positioned in self._iter_positioned_regions(resolved_layout, style_enabled=style_enabled):
            render = getattr(positioned.resolved.region, "render", None)
            if not callable(render):
                raise TypeError(
                    f"Registered region {positioned.resolved.region_id!r} does not provide render(context)."
                )

            region_buffer = render(positioned.context)
            if not isinstance(region_buffer, CellBuffer):
                raise TypeError(
                    f"Region {positioned.resolved.region_id!r} returned {type(region_buffer)!r}; expected CellBuffer."
                )

            frame.blit(
                region_buffer,
                dest_x=positioned.local_x,
                dest_y=positioned.local_y,
            )

        self._draw_layout_dividers_into_frame(frame, resolved_layout)

        return frame

    def compose_root_lines(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
        style_enabled: bool = True,
    ) -> list[str]:
        """Resolve and render the default root region as visible terminal rows."""

        resolved_layout = self._resolve_single_root_layout(columns=columns, lines=lines, viewport=viewport)
        resolved_region = resolved_layout.regions[0]
        region = resolved_region.region
        render_lines = getattr(region, "render_lines", None)
        if not callable(render_lines):
            raise TypeError(
                f"Registered root region {resolved_region.region_id!r} does not provide render_lines(context)."
            )

        positioned = next(self._iter_positioned_regions(resolved_layout, style_enabled=style_enabled))
        lines_out = render_lines(positioned.context)
        return [str(line) for line in lines_out]

    def compose_layout_lines(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
        style_enabled: bool = True,
    ) -> list[str]:
        """Compose all registered leaf regions into full-width root terminal rows."""

        resolved_layout = self._resolve_registered_layout(columns=columns, lines=lines, viewport=viewport)
        root_viewport = resolved_layout.root_viewport
        if root_viewport.height <= 0:
            return []

        row_segments: list[list[RowSegment]] = [[] for _ in range(root_viewport.height)]
        for positioned in self._iter_positioned_regions(resolved_layout, style_enabled=style_enabled):
            local_lines = self._render_region_lines(positioned.resolved, positioned.context)
            if not local_lines:
                continue

            start_y = line_region_start_row(
                height=positioned.resolved.viewport.height,
                line_count=len(local_lines),
                vertical_anchor=getattr(positioned.resolved.region, "vertical_anchor", "top"),
            )
            for offset, line in enumerate(local_lines):
                absolute_y = positioned.local_y + start_y + offset
                if absolute_y < 0 or absolute_y >= root_viewport.height:
                    continue
                row_segments[absolute_y].append(
                    RowSegment(
                        x=positioned.local_x,
                        width=positioned.resolved.viewport.width,
                        text=self._normalize_region_line(line, positioned.resolved.viewport.width),
                    )
                )

        self._append_layout_divider_segments(row_segments, resolved_layout)

        return [
            self._compose_row_from_segments(segments, root_viewport.width)
            for segments in row_segments
        ]

    def _resolve_layout(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> ResolvedLayout:
        """Resolve the active layout tree once for a root viewport."""

        _, resolved_layout = self._resolve_root_layout(columns=columns, lines=lines, viewport=viewport)
        return resolved_layout

    def _resolve_registered_layout(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> ResolvedCoordinatorLayout:
        """Resolve one layout tree and bind every leaf to a registered region."""

        root_viewport, resolved_layout = self._resolve_root_layout(
            columns=columns,
            lines=lines,
            viewport=viewport,
        )
        return ResolvedCoordinatorLayout(
            root_viewport=root_viewport,
            layout=resolved_layout,
            regions=self._bind_registered_regions(resolved_layout),
        )

    def _resolve_single_root_layout(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> ResolvedCoordinatorLayout:
        """Resolve one registered layout that must occupy the whole root viewport."""

        resolved_layout = self._resolve_registered_layout(columns=columns, lines=lines, viewport=viewport)
        if len(resolved_layout.regions) != 1 or resolved_layout.regions[0].viewport != resolved_layout.root_viewport:
            raise ValueError("compose_root_lines requires a single region that occupies the root viewport.")
        return resolved_layout

    def _resolve_root_viewport(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> Viewport:
        """Normalize caller-provided dimensions into one root viewport."""

        if viewport is not None:
            return viewport
        if columns is None or lines is None:
            raise ValueError("columns and lines are required when viewport is not provided.")
        return self.root_viewport(columns=columns, lines=lines)

    def _resolve_root_layout(
        self,
        *,
        columns: Optional[int] = None,
        lines: Optional[int] = None,
        viewport: Optional[Viewport] = None,
    ) -> tuple[Viewport, ResolvedLayout]:
        """Resolve the active layout tree once together with its root viewport."""

        root_viewport = self._resolve_root_viewport(columns=columns, lines=lines, viewport=viewport)
        return root_viewport, self._layout_root.resolve(root_viewport)

    def _bind_registered_regions(self, resolved_layout: ResolvedLayout) -> list[ResolvedRegion]:
        """Bind one resolved layout's leaf ids to registered region objects."""

        resolved_regions: list[ResolvedRegion] = []
        for region_id, region_viewport in resolved_layout.viewports.items():
            if region_id not in self._regions:
                raise KeyError(f"Layout references unregistered region id: {region_id!r}")
            resolved_regions.append(
                ResolvedRegion(
                    region_id=region_id,
                    region=self._regions[region_id],
                    viewport=region_viewport,
                )
            )
        return resolved_regions

    @staticmethod
    def _iter_positioned_regions(
        resolved_layout: ResolvedCoordinatorLayout,
        *,
        style_enabled: bool,
    ) -> Iterator[PositionedRegion]:
        """Yield registered regions with their render context and root-local offset."""

        for resolved in resolved_layout.regions:
            yield PositionedRegion(
                resolved=resolved,
                context=RenderContext(
                    viewport=resolved.viewport,
                    root_viewport=resolved_layout.root_viewport,
                    style_enabled=style_enabled,
                ),
                local_x=resolved.viewport.x - resolved_layout.root_viewport.x,
                local_y=resolved.viewport.y - resolved_layout.root_viewport.y,
            )

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

    def _render_region_lines(self, resolved: ResolvedRegion, context: RenderContext) -> list[str]:
        """Ask one registered region for line output in the transitional line backend."""

        render_lines = getattr(resolved.region, "render_lines", None)
        if not callable(render_lines):
            raise TypeError(
                f"Registered region {resolved.region_id!r} does not provide render_lines(context)."
            )

        return clip_rendered_lines(
            render_lines(context),
            height=context.viewport.height,
            vertical_anchor=getattr(resolved.region, "vertical_anchor", "top"),
        )

    @staticmethod
    def _normalize_region_line(line: str, width: int) -> str:
        """Clip or pad one rendered region row to the assigned viewport width."""

        width = max(0, int(width))
        if width <= 0:
            return ""

        rendered = str(line)
        current_width = visible_length(rendered)
        if current_width > width:
            clipped = truncate_ansi(rendered, width)
            if "\033[" not in rendered:
                return strip_ansi(clipped)
            return clipped
        if current_width < width:
            pad = " " * (width - current_width)
            if "\033[" in rendered and not rendered.endswith(ANSI_RESET):
                return f"{rendered}{ANSI_RESET}{pad}"
            return f"{rendered}{pad}"
        return rendered

    @staticmethod
    def _compose_row_from_segments(segments: Sequence[RowSegment], total_width: int) -> str:
        """Assemble one root terminal row from non-overlapping horizontal segments."""

        if total_width <= 0:
            return ""

        if not segments:
            return " " * total_width

        cursor = 0
        parts: list[str] = []
        for segment in sorted(segments, key=lambda item: item.x):
            if segment.x < cursor:
                raise ValueError("Overlapping row segments cannot be composed deterministically.")
            if segment.x > total_width:
                continue

            gap = segment.x - cursor
            if gap > 0:
                parts.append(" " * gap)
                cursor += gap

            remaining = max(0, total_width - cursor)
            if remaining <= 0:
                break

            width = min(segment.width, remaining)
            parts.append(RenderCoordinator._normalize_region_line(segment.text, width))
            cursor += width

        if cursor < total_width:
            parts.append(" " * (total_width - cursor))

        return "".join(parts)

    def _append_layout_divider_segments(
        self,
        row_segments: list[list[RowSegment]],
        resolved_layout: ResolvedCoordinatorLayout,
    ) -> None:
        """Append all layout divider rectangles to the row segment grid."""

        for divider in self._iter_clipped_dividers(resolved_layout):
            text = divider.fill * divider.width
            for row_offset in range(divider.height):
                absolute_y = divider.local_y + row_offset
                if absolute_y < 0 or absolute_y >= len(row_segments):
                    continue
                row_segments[absolute_y].append(
                    RowSegment(
                        x=divider.local_x,
                        width=divider.width,
                        text=text,
                    )
                )

    @staticmethod
    def _iter_clipped_dividers(
        resolved_layout: ResolvedCoordinatorLayout,
    ) -> Iterator[ClippedDivider]:
        """Yield all visible layout divider rectangles in root-local coordinates."""

        root_viewport = resolved_layout.root_viewport
        for divider in resolved_layout.layout.dividers:
            clipped = divider.viewport.intersection(root_viewport)
            if clipped.width <= 0 or clipped.height <= 0 or not divider.fill:
                continue
            yield ClippedDivider(
                local_x=clipped.x - root_viewport.x,
                local_y=clipped.y - root_viewport.y,
                width=clipped.width,
                height=clipped.height,
                fill=divider.fill[:1],
            )

    def _draw_layout_dividers_into_frame(
        self,
        frame: CellBuffer,
        resolved_layout: ResolvedCoordinatorLayout,
    ) -> None:
        """Fill all resolved layout dividers into one composed cell frame."""

        for divider in self._iter_clipped_dividers(resolved_layout):
            text = divider.fill * divider.width
            for row_offset in range(divider.height):
                frame.draw_text(divider.local_x, divider.local_y + row_offset, text)


__all__ = [
    "DEFAULT_ROOT_REGION_ID",
    "RenderCoordinator",
    "RenderCoordinatorState",
    "ResolvedRegion",
    "RowSegment",
]
