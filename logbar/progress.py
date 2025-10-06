# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import datetime
import sys
import time
from enum import Enum
from typing import Iterable, Optional, Union, TYPE_CHECKING
from warnings import warn

from . import LogBar
from .logbar import (
    attach_progress_bar,
    detach_progress_bar,
    _record_progress_activity,
    render_lock,
    render_progress_stack,
)

if TYPE_CHECKING:  # pragma: no cover - type hints without runtime import cycle
    from .logbar import LogBar as LogBarType
from .terminal import terminal_size
from .util import auto_iterable

logger = LogBar.shared()

# ANSI helpers for the animated title effect
ANSI_RESET = "\033[0m"
ANSI_BOLD_RESET = "\033[22m"
TITLE_BASE_COLOR = "\033[38;5;250m"
TITLE_HIGHLIGHT_COLOR = "\033[1m\033[38;5;15m"

# TODO FIXME: what does this do exactly?
class ProgressBarWarning(Warning):
    def __init__(self, msg, fp_write=None, *a, **k):
        if fp_write is not None:
            fp_write("\n" + self.__class__.__name__ + ": " + str(msg).rstrip() + '\n')
        else:
            super().__init__(msg, *a, **k)

class RenderMode(str, Enum):
    AUTO = "AUTO" # pb will auto draw() at the START of each itereation
    MANUAL = "MANUAL" # pb will not call draw() in each iteration and user must call draw()


class ProgressBar:
    def __init__(self, iterable: Union[Iterable, int, dict, set], owner: Optional["LogBarType"] = None):
        self._iterating = False # state: in init or active iteration

        self._render_mode = RenderMode.AUTO

        self._title = ""
        self._subtitle = ""
        self._fill = '█'
        self.closed = False # active state

        # max info length over the life ot the pb
        self.max_title_len = 0
        self.max_subtitle_len = 0

        # auto convert simple types into iterable
        auto_iter = auto_iterable(iterable)
        self.iterable = auto_iter if auto_iter else iterable

        self.bar_length = 0
        self.current_iter_step = 0
        self.time = time.time()
        self._title_animation_start = self.time
        self._title_animation_period = 0.1

        self.ui_show_left_steps = True # show [1 of 100] on left side
        self.ui_show_left_steps_offset = 0

        self._owner_logger = owner
        self._attached_logger: Optional["LogBarType"] = None
        self._attached = False
        self._last_rendered_line = ""

    def set(self,
            show_left_steps: Optional[bool] = None,
            left_steps_offset: Optional[int] = None,
            ):
        if show_left_steps is not None:
            self.ui_show_left_steps = show_left_steps

        if left_steps_offset is not None:
            self.ui_show_left_steps_offset = left_steps_offset
        return self

    def fill(self, fill = '█'):
        self._fill = fill
        return self

    def title(self, title:str):
        if self._iterating and self._render_mode != RenderMode.MANUAL:
            logger.warn("ProgressBar: Title should not be updated after iteration has started unless in `manual` render mode.")

        if len(title) > self.max_title_len:
            self.max_title_len = len(title)

        previous_title = self._title
        self._title = title

        # Only reset the animation clock when transitioning from no title to
        # an initial title. For dynamic titles (updated every frame) we want
        # to preserve the elapsed time so the highlight keeps sweeping across
        # the text instead of snapping back to the first character.
        if not previous_title and title:
            self._title_animation_start = time.time()
        return self

    def subtitle(self, subtitle: str):
        if self._iterating and self._render_mode != RenderMode.MANUAL:
            logger.warn("ProgressBar: Sub-title should not be updated after iteration has started unless in `manual` render mode.")

        if len(subtitle) > self.max_subtitle_len:
            self.max_subtitle_len = len(subtitle)

        self._subtitle = subtitle
        return self

    # set render mode
    def mode(self, mode: RenderMode):
        self._render_mode = mode

    def auto(self):
        self._render_mode = RenderMode.AUTO
        return self

    def manual(self ):
        self._render_mode = RenderMode.MANUAL
        return self

    def attach(self, logger: Optional["LogBarType"] = None):
        if self.closed:
            return self

        if self._attached:
            return self

        target_logger = logger or self._owner_logger or LogBar.shared()
        self._attached_logger = target_logger
        self._owner_logger = target_logger
        attach_progress_bar(self)
        self._attached = True
        with render_lock():
            render_progress_stack(lock_held=True)

        return self

    def detach(self):
        if not self._attached:
            return self

        with render_lock():
            detach_progress_bar(self)
            render_progress_stack(lock_held=True)

        self._attached = False
        self._attached_logger = None
        self._last_rendered_line = ""
        return self

    def draw(self):
        _record_progress_activity()
        if not self._attached:
            columns, _ = terminal_size()
            rendered_line = self._render_snapshot(columns)

            with render_lock():
                print(f'\r{rendered_line}', end='', flush=True)
            return

        columns, _ = terminal_size()
        rendered_line = self._render_snapshot(columns)

        with render_lock():
            render_progress_stack(
                lock_held=True,
                precomputed={self: rendered_line},
                columns_hint=columns,
            )

    def calc_time(self, iteration):
        used_time = int(time.time() - self.time)
        formatted_time = str(datetime.timedelta(seconds=used_time))
        remaining = str(datetime.timedelta(seconds=int((used_time / max(iteration, 1)) * len(self))))
        return f"{formatted_time} / {remaining}"

    def _render_snapshot(self, columns: Optional[int] = None) -> str:
        if columns is None:
            columns, _ = terminal_size()

        total_steps = len(self)
        effective_total = total_steps if total_steps else 1

        percent_num = self.step() / float(effective_total)
        percent = ("{0:.1f}").format(100 * percent_num)
        log_text = f"{self.calc_time(self.step())} [{self.step()}/{total_steps}] {percent}%"

        pre_bar_size = 0

        if self._title:
            pre_bar_size += self.max_title_len + 1
        if self._subtitle:
            pre_bar_size += self.max_subtitle_len + 1

        if self.ui_show_left_steps:
            left_current = self.step() - self.ui_show_left_steps_offset
            left_total = total_steps - self.ui_show_left_steps_offset
            self.ui_show_left_steps_text = f"[{left_current} of {left_total}] "
            self.ui_show_left_steps_text_max_len = len(self.ui_show_left_steps_text)
            pre_bar_size += self.ui_show_left_steps_text_max_len

        padding = ""

        if self._title and len(self._title) < self.max_title_len:
            padding += " " * (self.max_title_len - len(self._title))

        if self._subtitle and len(self._subtitle) < self.max_subtitle_len:
            padding += " " * (self.max_subtitle_len - len(self._subtitle))

        available_columns = columns if columns is not None and columns > 0 else 0

        bar_length = max(0, available_columns - pre_bar_size - len(log_text) - 2) if available_columns else 0
        filled_length = int(bar_length * self.step() // effective_total) if bar_length else 0
        bar = self._fill * filled_length + '-' * (bar_length - filled_length)

        rendered_line = self._render_line(
            bar=bar,
            log_text=log_text,
            pre_bar_padding=padding,
            columns=columns,
        )

        self._last_rendered_line = rendered_line
        return rendered_line

    def _render_line(self, bar: str, log_text: str, pre_bar_padding: str = "", columns: Optional[int] = None) -> str:
        segments_plain = []
        segments_rendered = []

        def append_segment(text: str, rendered: Optional[str] = None):
            segments_plain.append(text)
            segments_rendered.append(rendered if rendered is not None else text)

        animate_title = self._should_animate_title()

        if self._title:
            if animate_title:
                animated_title = self._animated_text(self._title)
                append_segment(self._title, animated_title)
            else:
                append_segment(self._title)
            append_segment(" ")

        if self._subtitle:
            append_segment(self._subtitle + " ")

        if pre_bar_padding:
            append_segment(pre_bar_padding)

        if self.ui_show_left_steps:
            left_steps_text = self.ui_show_left_steps_text
            if not self._title and animate_title:
                append_segment(left_steps_text, self._animated_text(left_steps_text))
            else:
                append_segment(left_steps_text)

        append_segment(f"{bar}| {log_text}")

        plain_out = ''.join(segments_plain)
        rendered_out = ''.join(segments_rendered)

        if columns is not None:
            if len(plain_out) > columns:
                plain_out = plain_out[:columns]
                rendered_out = self._truncate_ansi(rendered_out, columns)
            elif len(plain_out) < columns:
                pad = " " * (columns - len(plain_out))
                plain_out += pad
                rendered_out += pad

        return rendered_out

    def _animated_text(self, text: str) -> str:
        if not text:
            return ""

        period = self._title_animation_period
        elapsed = time.time() - self._title_animation_start
        highlight_idx = int(elapsed / max(period, 1e-6)) % max(len(text), 1)

        parts = [TITLE_BASE_COLOR]
        for idx, char in enumerate(text):
            if idx == highlight_idx:
                parts.append(TITLE_HIGHLIGHT_COLOR)
                parts.append(char)
                parts.append(ANSI_BOLD_RESET)
                parts.append(TITLE_BASE_COLOR)
            else:
                parts.append(char)

        parts.append(ANSI_RESET)
        return ''.join(parts)

    def _truncate_ansi(self, text: str, limit: int) -> str:
        if limit <= 0:
            # ensure we reset styles even if nothing is shown
            return ANSI_RESET

        result = []
        printable = 0
        i = 0
        while i < len(text) and printable < limit:
            char = text[i]
            if char == '\033':
                end = i + 1
                while end < len(text) and text[end] != 'm':
                    end += 1
                end = min(end + 1, len(text))
                result.append(text[i:end])
                i = end
                continue

            result.append(char)
            printable += 1
            i += 1

        # ensure the terminal color state is restored even if we sliced mid-sequence
        if printable >= limit:
            result.append(ANSI_RESET)

        return ''.join(result)

    def _should_animate_title(self) -> bool:
        isatty = getattr(sys.stdout, "isatty", None)
        if not callable(isatty):
            return False
        return bool(isatty())

    def __bool__(self):
        if self.iterable is None:
            raise TypeError('bool() undefined when iterable == total == None')
        return bool(self.iterable)

    def __len__(self):
        return (
            self.iterable.shape[0] if hasattr(self.iterable, "shape")
            else len(self.iterable) if hasattr(self.iterable, "__len__")
            else self.iterable.__length_hint__() if hasattr(self.iterable, "__length_hint__")
            else getattr(self, "total", None))

    # TODO FIXME: I have no cluse why the try/catch is catching nothing here
    def __reversed__(self):
        try:
            original = self.iterable
        except AttributeError:
            raise TypeError("'progress' object is not reversible")
        else:
            self.iterable = reversed(self.iterable)
            return self.__iter__()
        finally:
            self.iterable = original

    def __contains__(self, item):
        contains = getattr(self.iterable, '__contains__', None)
        return contains(item) if contains is not None else item in self.__iter__()

    def __enter__(self):
        return self

    # TODO FIXME: I don't understand the exception here. What are we catching? yield error?
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.close()
        except AttributeError:
            # maybe eager thread cleanup upon external error
            if (exc_type, exc_value, traceback) == (None, None, None):
                raise

            # TODO FIXME: what does this do exactly?
            warn("AttributeError ignored", ProgressBarWarning, stacklevel=2)

    def __del__(self):
        self.close()

    # TODO FIXME: what does this do exactly? where is this `pos` attr magically coming from? I don't see it anywhere
    @property
    def _comparable(self):
        return abs(getattr(self, "pos", 1 << 31))

    def __hash__(self):
        return id(self)

    def step(self) -> int:
        return self.current_iter_step

    def next(self):
        self.current_iter_step += 1
        return self

    def __iter__(self):
        iterable = self.iterable

        for obj in iterable:
            # update running state
            if not self._iterating:
                self.iterating = True

            self.next()

            if self._render_mode == RenderMode.AUTO:
                self.draw()

            yield obj

        self.close()
        return

    def close(self):
        if self.closed:
            return

        self.closed = True
        self.detach()
