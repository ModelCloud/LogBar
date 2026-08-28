# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

"""tqdm-compatible progress bar API backed by LogBar's ProgressBar."""

import sys
import time
from contextlib import contextmanager
from typing import Any, Optional

from .logbar import LogBar
from .progress import ProgressBar


class tqdm(ProgressBar):
    """Drop-in progress bar that mirrors the public ``tqdm`` API."""

    _lock: Any = None

    def __init__(
        self,
        iterable=None,
        desc: Optional[str] = None,
        total: Optional[int] = None,
        leave: bool = True,
        file=None,
        ncols: Optional[int] = None,
        mininterval: float = 0.1,
        maxinterval: float = 10.0,
        miniters: Optional[int] = None,
        ascii: Optional[bool] = None,
        disable: bool = False,
        unit: str = "it",
        unit_scale: bool = False,
        dynamic_ncols: bool = False,
        smoothing: float = 0.3,
        bar_format: Optional[str] = None,
        initial: int = 0,
        position: Optional[int] = None,
        postfix: Optional[dict[str, Any]] = None,
        unit_divisor: int = 1000,
        write_bytes: Optional[bool] = None,
        lock_args=None,
        nrows: Optional[int] = None,
        colour: Optional[str] = None,
        delay: float = 0,
        gui: bool = False,
        **kwargs: Any,
    ):
        self.disable = disable
        self.unit = unit
        self.leave = leave
        self.file = file
        self._initial = initial
        self._start = time.time()

        if iterable is None and total is None:
            resolved_iterable = None
        elif iterable is None:
            resolved_iterable = range(total)
        else:
            resolved_iterable = iterable

        if total is None and resolved_iterable is not None:
            try:
                total = len(resolved_iterable)
            except Exception:
                total = None

        self.total = total

        owner = LogBar.shared()
        super().__init__(resolved_iterable, owner=owner, output_interval=1)

        self.current_iter_step = initial

        if not disable:
            self.attach(owner)

        if desc:
            self.title(desc)

        if postfix:
            self.set_postfix(postfix, refresh=False)

    def __len__(self) -> Optional[int]:
        if self.total is not None:
            return self.total
        return super().__len__()

    def __iter__(self):
        if self.iterable is None:
            raise TypeError("'tqdm' object is not iterable")
        yield from super().__iter__()

    def update(self, n: int = 1) -> None:
        if self.disable or n is None:
            return
        if n == 0:
            return
        self.current_iter_step = max(0, self.current_iter_step + n)
        self.draw()

    def draw(self, force: bool = False) -> None:
        if self.disable:
            return
        if self.total is None and self.iterable is not None:
            # LogBar needs a known total to render a meaningful determinate bar.
            return
        super().draw(force=force)

    def close(self) -> None:
        if self.disable or self.closed:
            return
        super().close()

    def set_description(self, desc: Optional[str] = None, refresh: bool = True) -> None:
        if desc is not None:
            self.title(desc)
            if refresh:
                self.draw()

    def set_postfix(self, ordered_dict: Optional[dict[str, Any]] = None, refresh: bool = True, **kwargs: Any) -> None:
        postfix = ordered_dict or kwargs
        if postfix:
            subtitle = ", ".join(f"{k}={v}" for k, v in postfix.items())
            self.subtitle(subtitle)
            if refresh:
                self.draw()

    @property
    def n(self) -> int:
        return self.current_iter_step

    @n.setter
    def n(self, value: int) -> None:
        self.current_iter_step = value

    @property
    def format_dict(self) -> dict[str, Any]:
        elapsed = max(0.0, time.time() - self._start)
        completed = max(0, self.current_iter_step - self._initial)
        rate = completed / elapsed if elapsed > 0 else 0
        return {
            "n": self.current_iter_step,
            "total": self.total,
            "elapsed": elapsed,
            "rate": rate,
        }

    @classmethod
    def set_lock(cls, lock: Any) -> None:
        cls._lock = lock

    @classmethod
    def get_lock(cls) -> Any:
        return cls._lock

    @classmethod
    def write(cls, s: str, file=None, end: str = "\n", nolock: bool = False) -> None:
        file = file or sys.stdout
        file.write(s + end)
        try:
            file.flush()
        except Exception:
            pass


def trange(*args: Any, **kwargs: Any) -> tqdm:
    """Shorthand for ``tqdm(range(...))``."""

    return tqdm(range(*args), **kwargs)


@contextmanager
def logging_redirect_tqdm(loggers: Any = None, tqdm_class: Any = None):
    """No-op context manager kept for ``tqdm`` API compatibility."""

    yield
