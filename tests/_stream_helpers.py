# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Shared stream fixtures for region screen and split-session tests."""

from __future__ import annotations

import io


class FakeTTY(io.StringIO):
    """String buffer that reports TTY support for ANSI render tests."""

    def isatty(self):
        """Pretend to be a cursor-capable terminal."""

        return True


class FakePipe(io.StringIO):
    """String buffer that behaves like a plain redirected stream."""

    def isatty(self):
        """Report non-interactive stream mode."""

        return False


class MirroredTTY(FakeTTY):
    """TTY-like buffer that can also mirror writes to a real terminal device."""

    def __init__(self, mirror: io.TextIOBase | None = None):
        """Capture output in-memory while optionally forwarding it live."""

        super().__init__()
        self._mirror = mirror

    def write(self, s):
        """Write to the in-memory buffer and the live terminal when present."""

        if self._mirror is not None:
            self._mirror.write(s)
            self._mirror.flush()
        return super().write(s)

    def flush(self):
        """Flush the mirrored terminal stream if one is attached."""

        if self._mirror is not None:
            self._mirror.flush()
        return super().flush()

    def fileno(self):
        """Expose the mirrored terminal file descriptor for size probing."""

        if self._mirror is None:
            raise OSError("No mirrored terminal is attached.")
        return self._mirror.fileno()

    def close(self):
        """Close the mirrored terminal handle after the buffered stream ends."""

        mirror = self._mirror
        self._mirror = None
        try:
            if mirror is not None:
                mirror.flush()
                mirror.close()
        finally:
            return super().close()


def real_terminal_stream():
    """Return a live terminal-backed buffer when `/dev/tty` is available."""

    try:
        mirror = open("/dev/tty", "w", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return FakeTTY()
    return MirroredTTY(mirror=mirror)


__all__ = ["FakePipe", "FakeTTY", "MirroredTTY", "real_terminal_stream"]
