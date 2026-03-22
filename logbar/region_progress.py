# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Pane-local progress helpers for split-pane region screen sessions."""

from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

from .progress import ProgressBar, RollingProgressBar

if TYPE_CHECKING:  # pragma: no cover - type hints without runtime import cycle
    from .session import RegionScreenSession


class RegionProgressBar(ProgressBar):
    """Progress bar that renders into one session pane footer."""

    def __init__(
        self,
        iterable,
        *,
        session: "RegionScreenSession",
        region_id: str,
        output_interval: Optional[int] = None,
    ) -> None:
        """Bind one determinate progress bar to a split-pane session region."""

        super().__init__(iterable=iterable, owner=None, output_interval=output_interval)
        self._session = session
        self._region_id = str(region_id).strip() or session.coordinator.root_region_id

    @property
    def region_id(self) -> str:
        """Return the pane identifier this progress bar renders into."""

        return self._region_id

    def _mark_dirty(self):
        """Mark the pane-local bar dirty and optionally refresh the session."""

        if self._attached:
            self._session._mark_progress_bar_dirty(self._region_id, self)
        return self

    def attach(self, logger=None):
        """Attach the bar to its pane-local footer instead of the global stack."""

        del logger

        if self.closed or self._attached:
            return self

        self._attached = True
        self._attached_logger = None
        self._owner_logger = None
        self._next_title_refresh_at = 0.0
        self._session._attach_progress_bar(self._region_id, self)
        return self

    def detach(self):
        """Detach the bar from its pane-local footer."""

        if not self._attached:
            return self

        self._session._detach_progress_bar(self._region_id, self)
        self._attached = False
        self._attached_logger = None
        self._last_rendered_line = ""
        self._next_title_refresh_at = 0.0
        return self

    def draw(self, force: bool = False):
        """Resolve and optionally paint the pane-local progress footer."""

        self._session._draw_progress_bar(self._region_id, self, force=force)


class RegionRollingProgressBar(RollingProgressBar):
    """Rolling spinner that renders into one session pane footer."""

    def __init__(
        self,
        *,
        session: "RegionScreenSession",
        region_id: str,
        interval: float = 0.5,
        tail_length: int = 4,
    ) -> None:
        """Bind one rolling spinner to a split-pane session region."""

        super().__init__(owner=None, interval=interval, tail_length=tail_length)
        self._session = session
        self._region_id = str(region_id).strip() or session.coordinator.root_region_id

    @property
    def region_id(self) -> str:
        """Return the pane identifier this spinner renders into."""

        return self._region_id

    def _mark_dirty(self):
        """Mark the pane-local spinner dirty and optionally refresh the session."""

        if self._attached:
            self._session._mark_progress_bar_dirty(self._region_id, self)
        return self

    def attach(self, logger=None):
        """Attach the spinner to its pane-local footer."""

        del logger

        if self.closed or self._attached:
            return self

        self._attached = True
        self._attached_logger = None
        self._owner_logger = None
        self._next_title_refresh_at = 0.0
        self._next_spinner_refresh_at = time.monotonic() + self._interval
        self._session._attach_progress_bar(self._region_id, self)
        return self

    def detach(self):
        """Detach the spinner from its pane-local footer."""

        if not self._attached:
            return self

        self._next_spinner_refresh_at = 0.0
        self._session._detach_progress_bar(self._region_id, self)
        self._attached = False
        self._attached_logger = None
        self._last_rendered_line = ""
        self._next_title_refresh_at = 0.0
        return self

    def draw(self, force: bool = False):
        """Resolve and optionally paint the pane-local spinner footer."""

        self._session._draw_progress_bar(self._region_id, self, force=force)


__all__ = ["RegionProgressBar", "RegionRollingProgressBar"]
