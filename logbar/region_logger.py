# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Region-bound logger helpers for split-pane render experiments."""

from __future__ import annotations

from typing import Optional, Sequence, Union

from .logbar import LEVEL, LogBar, _RENDER_LOCK, _level_prefix
from .region import LogRegion


class RegionLogBar(LogBar):
    """Experimental logger that appends formatted output into one LogRegion."""

    def __init__(
        self,
        name: str,
        region: Optional[LogRegion] = None,
        *,
        supports_ansi: bool = True,
    ) -> None:
        """Bind the logger to one pane region instead of the process stdout."""

        super().__init__(name)
        self._region = region if region is not None else LogRegion()
        self._supports_ansi = bool(supports_ansi)

    @property
    def region(self) -> LogRegion:
        """Return the bound pane region."""

        return self._region

    @property
    def supports_ansi(self) -> bool:
        """Return whether log prefixes should include ANSI styling."""

        return self._supports_ansi

    def bind_region(self, region: LogRegion) -> "RegionLogBar":
        """Rebind the logger to a different LogRegion."""

        if not isinstance(region, LogRegion):
            raise TypeError("region must be a LogRegion instance.")
        self._region = region
        return self

    def set_footer_lines(self, lines: Sequence[str]) -> "RegionLogBar":
        """Replace the region footer rows."""

        self._region.set_footer_lines(lines)
        return self

    def append_footer_line(self, line: str) -> "RegionLogBar":
        """Append one footer row to the bound region."""

        self._region.append_footer_line(line)
        return self

    def clear_footer(self) -> "RegionLogBar":
        """Remove all footer content from the bound region."""

        self._region.clear_footer()
        return self

    def clear_body(self) -> "RegionLogBar":
        """Remove all body log rows from the bound region."""

        self._region.clear_body()
        return self

    def clear(self) -> "RegionLogBar":
        """Reset both body and footer content for the bound region."""

        self._region.clear_body()
        self._region.clear_footer()
        return self

    def _emit_log_line_locked(
        self,
        normalized_level: int,
        level_label: str,
        str_msg: str,
        *,
        allow_defer: bool = True,
        backend_state: Optional[object] = None,
    ) -> None:
        """Append one formatted log entry into the bound region."""

        del normalized_level, allow_defer, backend_state

        prefix = _level_prefix(level_label, self._supports_ansi)
        message_lines = str(str_msg).splitlines() or [""]
        for line in message_lines:
            self._region.append_body_line(f"{prefix}{line}")

    def _process(self, level: Union[LEVEL, int, str], msg, *args, **kwargs):
        """Format and append one log entry into the bound region."""

        del kwargs

        normalized_level = self._normalize_level(level)
        if not self.isEnabledFor(normalized_level):
            return

        level_label = self._level_label(level, normalized_level)
        str_msg = self._format_message(msg, args)

        with _RENDER_LOCK:
            self._emit_log_line_locked(
                normalized_level,
                level_label,
                str_msg,
                allow_defer=False,
                backend_state=None,
            )


__all__ = ["RegionLogBar"]
