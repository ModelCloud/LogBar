# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Rectangular layout primitives for future region-based renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Union


@dataclass(frozen=True)
class Viewport:
    """Describe a rectangular terminal region in absolute cell coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        """Clamp invalid dimensions so downstream layout math stays safe."""

        object.__setattr__(self, "width", max(0, int(self.width)))
        object.__setattr__(self, "height", max(0, int(self.height)))
        object.__setattr__(self, "x", int(self.x))
        object.__setattr__(self, "y", int(self.y))

    @property
    def right(self) -> int:
        """Return the exclusive right edge of the rectangle."""

        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Return the exclusive bottom edge of the rectangle."""

        return self.y + self.height

    def translate(self, dx: int = 0, dy: int = 0) -> "Viewport":
        """Return a copy moved by the given terminal-cell offset."""

        return Viewport(self.x + int(dx), self.y + int(dy), self.width, self.height)

    def inset(self, *, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0) -> "Viewport":
        """Shrink the rectangle by edge offsets while preserving non-negative size."""

        left = max(0, int(left))
        top = max(0, int(top))
        right = max(0, int(right))
        bottom = max(0, int(bottom))

        width = max(0, self.width - left - right)
        height = max(0, self.height - top - bottom)
        return Viewport(self.x + left, self.y + top, width, height)

    def intersection(self, other: "Viewport") -> "Viewport":
        """Return the clipped overlap of two rectangles."""

        left = max(self.x, other.x)
        top = max(self.y, other.y)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        return Viewport(left, top, max(0, right - left), max(0, bottom - top))


class SplitDirection(str, Enum):
    """Supported split directions for a rectangular region tree."""

    LEFT_RIGHT = "LEFT_RIGHT"
    TOP_BOTTOM = "TOP_BOTTOM"


@dataclass(frozen=True)
class LayoutAssignment:
    """Bind one leaf region identifier to a concrete viewport."""

    region_id: str
    viewport: Viewport


@dataclass(frozen=True)
class DividerAssignment:
    """Bind one split-divider rectangle to its repeated fill character."""

    viewport: Viewport
    fill: str

    def __post_init__(self) -> None:
        """Normalize the divider fill to a single visible character when present."""

        text = str(self.fill or "")
        object.__setattr__(self, "fill", text[:1])


@dataclass(frozen=True)
class ResolvedLayout:
    """Store all leaf viewports and divider rectangles from one layout pass."""

    viewports: Dict[str, Viewport]
    dividers: List[DividerAssignment]


class LayoutNode:
    """Base class for nodes that can resolve into leaf viewports."""

    def resolve(self, viewport: Viewport) -> ResolvedLayout:
        """Return all leaf viewports and dividers under this node."""

        raise NotImplementedError

    def assign(self, viewport: Viewport) -> List[LayoutAssignment]:
        """Return all leaf viewport assignments under this node."""

        resolved = self.resolve(viewport)
        return [
            LayoutAssignment(region_id=region_id, viewport=region_viewport)
            for region_id, region_viewport in resolved.viewports.items()
        ]

    def dividers(self, viewport: Viewport) -> List[DividerAssignment]:
        """Return all divider rectangles under this node."""

        return list(self.resolve(viewport).dividers)


@dataclass(frozen=True)
class LeafNode(LayoutNode):
    """Terminal layout leaf that names one renderable region."""

    region_id: str

    def resolve(self, viewport: Viewport) -> ResolvedLayout:
        """Resolve a leaf directly to the provided viewport."""

        return ResolvedLayout(
            viewports={self.region_id: viewport},
            dividers=[],
        )


LayoutChild = Union[str, LayoutNode]


def pane(region_id: str) -> LeafNode:
    """Create one leaf layout node from a public region identifier."""

    normalized = str(region_id).strip()
    if not normalized:
        raise ValueError("region_id must not be empty.")
    return LeafNode(normalized)


def _coerce_layout_child(child: LayoutChild) -> LayoutNode:
    """Normalize bare region ids and existing layout nodes into one node."""

    if isinstance(child, LayoutNode):
        return child
    if isinstance(child, str):
        return pane(child)
    raise TypeError("layout children must be region-id strings or LayoutNode instances.")


def _normalize_weights(children: Sequence[LayoutNode], weights: Optional[Sequence[int]]) -> List[int]:
    """Resolve child weights while rejecting zero or negative sizes."""

    if not children:
        raise ValueError("SplitNode requires at least one child.")

    if weights is None:
        return [1] * len(children)

    if len(weights) != len(children):
        raise ValueError("weights must match the number of children.")

    normalized = [int(weight) for weight in weights]
    if any(weight <= 0 for weight in normalized):
        raise ValueError("weights must be positive integers.")
    return normalized


def _allocate_lengths(total: int, weights: Sequence[int]) -> List[int]:
    """Distribute terminal cells proportionally and deterministically."""

    total = max(0, int(total))
    if not weights:
        return []

    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0] * len(weights)

    lengths = [(total * weight) // weight_sum for weight in weights]
    remainder = total - sum(lengths)
    for index in range(remainder):
        lengths[index % len(lengths)] += 1
    return lengths


@dataclass(frozen=True)
class SplitNode(LayoutNode):
    """Internal layout node that divides a rectangle among child nodes."""

    direction: SplitDirection
    children: Sequence[LayoutNode]
    weights: Optional[Sequence[int]] = None
    gutter: int = 1
    divider: Optional[str] = None
    _resolved_weights: List[int] = field(init=False, repr=False)
    _resolved_divider: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate split configuration eagerly so resolution stays simple."""

        object.__setattr__(self, "gutter", max(0, int(self.gutter)))
        object.__setattr__(
            self,
            "_resolved_weights",
            _normalize_weights(self.children, self.weights),
        )
        divider = self.divider
        if divider is None:
            divider = "|" if self.direction == SplitDirection.LEFT_RIGHT else "-"
        object.__setattr__(self, "_resolved_divider", str(divider or "")[:1])

    def resolve(self, viewport: Viewport) -> ResolvedLayout:
        """Resolve all descendant leaves and split dividers in one traversal."""

        if len(self.children) == 1:
            return self.children[0].resolve(viewport)

        resolved_viewports: Dict[str, Viewport] = {}
        resolved_dividers: List[DividerAssignment] = []
        child_viewports = self._child_viewports(viewport)
        for index, (child, child_viewport) in enumerate(child_viewports):
            child_resolved = child.resolve(child_viewport)
            for region_id, resolved_viewport in child_resolved.viewports.items():
                if region_id in resolved_viewports:
                    raise ValueError(f"Duplicate region id in layout tree: {region_id!r}")
                resolved_viewports[region_id] = resolved_viewport
            resolved_dividers.extend(child_resolved.dividers)
            if index >= len(child_viewports) - 1 or self.gutter <= 0 or not self._resolved_divider:
                continue
            if self.direction == SplitDirection.LEFT_RIGHT:
                resolved_dividers.append(
                    DividerAssignment(
                        viewport=Viewport(child_viewport.right, viewport.y, self.gutter, viewport.height),
                        fill=self._resolved_divider,
                    )
                )
            elif self.direction == SplitDirection.TOP_BOTTOM:
                resolved_dividers.append(
                    DividerAssignment(
                        viewport=Viewport(viewport.x, child_viewport.bottom, viewport.width, self.gutter),
                        fill=self._resolved_divider,
                    )
                )
            else:
                raise ValueError(f"Unsupported split direction: {self.direction!r}")
        return ResolvedLayout(
            viewports=resolved_viewports,
            dividers=resolved_dividers,
        )

    def _child_viewports(self, viewport: Viewport) -> List[tuple[LayoutNode, Viewport]]:
        """Resolve direct child rectangles for one split node."""

        if self.direction == SplitDirection.LEFT_RIGHT:
            return self._left_right_child_viewports(viewport)
        if self.direction == SplitDirection.TOP_BOTTOM:
            return self._top_bottom_child_viewports(viewport)
        raise ValueError(f"Unsupported split direction: {self.direction!r}")

    def _left_right_child_viewports(self, viewport: Viewport) -> List[tuple[LayoutNode, Viewport]]:
        """Split one viewport into left-to-right child rectangles."""

        available = max(0, viewport.width - (self.gutter * (len(self.children) - 1)))
        widths = _allocate_lengths(available, self._resolved_weights)

        child_viewports: List[tuple[LayoutNode, Viewport]] = []
        cursor_x = viewport.x
        for child, width in zip(self.children, widths):
            child_viewport = Viewport(cursor_x, viewport.y, width, viewport.height)
            child_viewports.append((child, child_viewport))
            cursor_x += width + self.gutter
        return child_viewports

    def _top_bottom_child_viewports(self, viewport: Viewport) -> List[tuple[LayoutNode, Viewport]]:
        """Split one viewport into top-to-bottom child rectangles."""

        available = max(0, viewport.height - (self.gutter * (len(self.children) - 1)))
        heights = _allocate_lengths(available, self._resolved_weights)

        child_viewports: List[tuple[LayoutNode, Viewport]] = []
        cursor_y = viewport.y
        for child, height in zip(self.children, heights):
            child_viewport = Viewport(viewport.x, cursor_y, viewport.width, height)
            child_viewports.append((child, child_viewport))
            cursor_y += height + self.gutter
        return child_viewports


def resolve_layout(root: LayoutNode, viewport: Viewport) -> Dict[str, Viewport]:
    """Resolve a layout tree into a stable mapping of region ids to rectangles."""

    return dict(root.resolve(viewport).viewports)


def resolve_dividers(root: LayoutNode, viewport: Viewport) -> List[DividerAssignment]:
    """Resolve all split-divider rectangles for one layout tree."""

    return list(root.resolve(viewport).dividers)


def columns(
    *children: LayoutChild,
    weights: Optional[Sequence[int]] = None,
    gutter: int = 1,
    divider: Optional[str] = None,
) -> SplitNode:
    """Create a left-to-right split from region ids or nested layout nodes."""

    return SplitNode(
        direction=SplitDirection.LEFT_RIGHT,
        children=tuple(_coerce_layout_child(child) for child in children),
        weights=weights,
        gutter=gutter,
        divider=divider,
    )


def rows(
    *children: LayoutChild,
    weights: Optional[Sequence[int]] = None,
    gutter: int = 1,
    divider: Optional[str] = None,
) -> SplitNode:
    """Create a top-to-bottom split from region ids or nested layout nodes."""

    return SplitNode(
        direction=SplitDirection.TOP_BOTTOM,
        children=tuple(_coerce_layout_child(child) for child in children),
        weights=weights,
        gutter=gutter,
        divider=divider,
    )


__all__ = [
    "DividerAssignment",
    "LayoutAssignment",
    "LayoutChild",
    "LayoutNode",
    "LeafNode",
    "ResolvedLayout",
    "SplitDirection",
    "SplitNode",
    "Viewport",
    "columns",
    "pane",
    "rows",
    "resolve_layout",
]
