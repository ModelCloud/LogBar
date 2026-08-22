# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""Utilities for providing buffered stdout behavior when needed."""

from __future__ import annotations

import io
import queue
import sys
import threading
import weakref
from typing import Optional, Tuple

QueueItem = Tuple[str, Optional[str], Optional[threading.Event]]

_CACHE_LOCK = threading.Lock()
_CACHED_WRAPPERS: dict[int, Tuple[Optional[weakref.ReferenceType[object]], "QueueingStdout"]] = {}


class QueueingStdout:
    """Proxy stdout that funnels writes through a background flush thread."""

    def __init__(self, stream: object):
        """Wrap an unbuffered-like stream so writes are serialized off-thread."""

        try:
            self._stream_ref: Optional[weakref.ReferenceType[object]] = weakref.ref(stream)  # type: ignore[arg-type]
        except TypeError:
            self._stream_ref = None
            self._stream = stream
        else:
            self._stream = None
            # The cache retains wrappers, so release the worker and wrapper's
            # stream reference when a weak-referenceable stream is collected.
            weakref.finalize(stream, self.close)
        self._queue: "queue.Queue[QueueItem]" = queue.Queue()
        self._closed = False
        self._state_lock = threading.Lock()
        self._close_event: Optional[threading.Event] = None
        self._logbar_queue_wrapped = True
        self._worker = threading.Thread(
            target=self._drain_worker,
            name="logbar-stdout-flush",
            daemon=True,
        )
        self._worker.start()

    def _target_stream(self) -> object:
        """Return the wrapped stream, failing clearly if it was collected."""

        if self._stream_ref is not None:
            stream = self._stream_ref()
            if stream is None:
                raise ValueError("underlying stream has been collected")
            return stream
        return self._stream

    def write(self, data):  # type: ignore[override]
        """Queue a write and return the character count immediately."""

        if not isinstance(data, str):
            data = str(data)

        if not data:
            return 0

        with self._state_lock:
            if self._closed:
                raise ValueError("I/O operation on closed file.")
            self._queue.put(("write", data, None))
        return len(data)

    def writelines(self, lines):  # type: ignore[override]
        """Queue multiple lines using the single-write path for each entry."""

        for line in lines:
            self.write(line)

    def flush(self):  # type: ignore[override]
        """Block until queued writes are flushed to the wrapped stream."""

        event = threading.Event()
        with self._state_lock:
            if self._closed:
                raise ValueError("flush of closed file")
            self._queue.put(("flush", None, event))
        event.wait()

    def close(self):  # type: ignore[override]
        """Drain pending output and stop the worker thread."""

        with self._state_lock:
            if self._closed:
                event = self._close_event
                if event is None:
                    return
            else:
                # Mark closed before queueing the sentinel so no later write or
                # flush can be placed behind the worker's shutdown request.
                self._closed = True
                event = threading.Event()
                self._close_event = event
                self._queue.put(("close", None, event))
        event.wait()

    @property
    def closed(self):  # type: ignore[override]
        """Mirror the standard file-like `closed` attribute."""

        with self._state_lock:
            return self._closed

    def fileno(self):  # type: ignore[override]
        """Expose `fileno()` when the wrapped stream supports it."""

        fileno = getattr(self._target_stream(), "fileno", None)
        if callable(fileno):
            return fileno()
        raise AttributeError("underlying stream does not provide fileno")

    def isatty(self):  # type: ignore[override]
        """Delegate TTY detection to the wrapped stream when possible."""

        method = getattr(self._target_stream(), "isatty", None)
        if callable(method):
            return method()
        return False

    def readable(self):  # type: ignore[override]
        """Mirror the wrapped stream readability capability."""

        method = getattr(self._target_stream(), "readable", None)
        if callable(method):
            return method()
        return False

    def writable(self):  # type: ignore[override]
        """Advertise write support because this wrapper only proxies writes."""

        return True

    def seekable(self):  # type: ignore[override]
        """Mirror the wrapped stream seekability when available."""

        method = getattr(self._target_stream(), "seekable", None)
        if callable(method):
            return method()
        return False

    def _drain_worker(self) -> None:
        """Continuously drain queued writes, flushes, and close requests."""

        while True:
            action, payload, event = self._queue.get()

            try:
                if action == "write":
                    if payload:
                        stream = self._target_stream()
                        stream.write(payload)
                        flush = getattr(stream, "flush", None)
                        if callable(flush):
                            flush()
                elif action == "flush":
                    flush = getattr(self._target_stream(), "flush", None)
                    if callable(flush):
                        flush()
                    if event is not None:
                        event.set()
                elif action == "close":
                    flush = getattr(self._target_stream(), "flush", None)
                    if callable(flush):
                        flush()
                    if event is not None:
                        event.set()
                    break
            except Exception:
                if event is not None:
                    event.set()
                if action == "close":
                    break
                continue

            if event is not None and action not in {"flush", "close"}:
                event.set()

            # Do not retain a stream through the blocking queue.get() call;
            # otherwise a worker can keep a short-lived redirected stream alive
            # even though the wrapper only stores a weak reference to it.
            stream = None
            flush = None

    def __getattr__(self, item):
        """Fall back to the wrapped stream for unknown attributes."""

        return getattr(self._target_stream(), item)


def _stdout_is_buffered(stream: object) -> bool:
    """Heuristically detect streams that already provide useful buffering."""

    if getattr(stream, "_logbar_queue_wrapped", False):
        return True

    if isinstance(stream, io.StringIO):
        return True

    write_through = getattr(stream, "write_through", False)
    if write_through:
        return False

    buffer_attr = getattr(stream, "buffer", None)
    return buffer_attr is not None


def get_buffered_stdout(stream: Optional[object] = None) -> object:
    """Return a cached queueing wrapper only when the stream needs one."""

    base = stream if stream is not None else sys.stdout

    if getattr(base, "_logbar_queue_wrapped", False):
        return base

    if _stdout_is_buffered(base):
        return base

    base_id = id(base)

    with _CACHE_LOCK:
        cached = _CACHED_WRAPPERS.get(base_id)
        if cached is not None:
            base_ref, wrapper = cached
            cached_base = base_ref() if base_ref is not None else None
            if base_ref is None or cached_base is base:
                if not wrapper.closed:
                    return wrapper
                _CACHED_WRAPPERS.pop(base_id, None)
            elif cached_base is None:
                _CACHED_WRAPPERS.pop(base_id, None)

        wrapper = QueueingStdout(base)
        try:
            def _evict(_ref, *, stream_id=base_id) -> None:
                """Drop a cached wrapper when its underlying stream is gone."""

                with _CACHE_LOCK:
                    cached_entry = _CACHED_WRAPPERS.get(stream_id)
                    if cached_entry is not None and cached_entry[0] is _ref:
                        _CACHED_WRAPPERS.pop(stream_id, None)

            base_ref = weakref.ref(base, _evict)  # type: ignore[arg-type]
        except TypeError:
            base_ref = None
        _CACHED_WRAPPERS[base_id] = (base_ref, wrapper)
        return wrapper


__all__ = ["QueueingStdout", "get_buffered_stdout"]
