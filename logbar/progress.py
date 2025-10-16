# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import datetime
import re
import sys
import time
import threading
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Optional, Union, TYPE_CHECKING, Sequence
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

# ANSI helpers for the animated title effect + colour styling
ANSI_RESET = "\033[0m"
ANSI_BOLD_RESET = "\033[22m"
TITLE_BASE_COLOR = "\033[38;5;250m"
TITLE_HIGHLIGHT_COLOR = "\033[1m\033[38;5;15m"


def _fg_256(code: int) -> str:
    return f"\033[38;5;{code}m"


def _fg_rgb(red: int, green: int, blue: int) -> str:
    return f"\033[38;2;{red};{green};{blue}m"


def _clamp_rgb(value: int) -> int:
    return max(0, min(255, value))


def _resolve_color(color: Optional[str]) -> str:
    if not color:
        return ""

    if color.startswith("\033["):
        return color

    named = _STYLE_COLOR_NAMES.get(color.lower()) if isinstance(color, str) else None
    if named:
        return named

    if isinstance(color, str) and color.isdigit():
        return _fg_256(int(color))

    if isinstance(color, str):
        hex_match = re.fullmatch(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color)
        if hex_match:
            hex_value = hex_match.group(1)
            if len(hex_value) == 3:
                r, g, b = (int(ch * 2, 16) for ch in hex_value)
            else:
                r = int(hex_value[0:2], 16)
                g = int(hex_value[2:4], 16)
                b = int(hex_value[4:6], 16)
            return _fg_rgb(_clamp_rgb(r), _clamp_rgb(g), _clamp_rgb(b))

    return str(color)


@dataclass(frozen=True)
class ProgressStyle:
    name: str
    fill_char: str = "█"
    empty_char: str = "-"
    fill_colors: Sequence[str] = ()
    empty_color: str = ""
    gradient: bool = False
    head_char: Optional[str] = None
    head_color: Optional[str] = None

    def with_fill_char(self, char: str) -> "ProgressStyle":
        return replace(self, fill_char=char)

    def with_empty_char(self, char: str) -> "ProgressStyle":
        return replace(self, empty_char=char)

    def with_colors(
        self,
        fill: Optional[Sequence[str]] = None,
        empty: Optional[str] = None,
        gradient: Optional[bool] = None,
        head_color: Optional[str] = None,
    ) -> "ProgressStyle":
        style = self
        if fill is not None:
            style = replace(style, fill_colors=tuple(fill))
        if empty is not None:
            style = replace(style, empty_color=empty)
        if gradient is not None:
            style = replace(style, gradient=gradient)
        if head_color is not None:
            style = replace(style, head_color=head_color)
        return style

    def with_head_char(self, char: Optional[str]) -> "ProgressStyle":
        return replace(self, head_char=char)

    def render(self, filled: int, empty: int) -> tuple[str, str]:
        # Build the plain-text representation (no ANSI) first.
        if self.head_char and filled > 0:
            plain_fill = self.fill_char * max(filled - 1, 0) + self.head_char
        else:
            plain_fill = self.fill_char * filled
        plain_empty = self.empty_char * empty
        plain_bar = plain_fill + plain_empty

        rendered_segments: list[str] = []

        def select_color(idx: int, total: int) -> str:
            if not self.fill_colors:
                return ""
            palette = self.fill_colors
            if self.gradient and len(palette) > 1 and total > 1:
                pos = idx / (total - 1)
                palette_index = min(int(pos * (len(palette) - 1)), len(palette) - 1)
                return palette[palette_index]
            return palette[idx % len(palette)]

        current_color: Optional[str] = None
        for idx in range(filled):
            desired_color = select_color(idx, filled)
            if self.head_color and idx == filled - 1:
                desired_color = self.head_color

            if desired_color != current_color:
                if current_color:
                    rendered_segments.append(ANSI_RESET)
                if desired_color:
                    rendered_segments.append(desired_color)
                current_color = desired_color

            rendered_segments.append(plain_fill[idx])

        if current_color:
            rendered_segments.append(ANSI_RESET)
            current_color = None

        if empty and self.empty_color:
            rendered_segments.append(self.empty_color)
            rendered_segments.append(plain_empty)
            rendered_segments.append(ANSI_RESET)
        else:
            rendered_segments.append(plain_empty)

        rendered_bar = ''.join(rendered_segments)

        return plain_bar, rendered_bar


def _register_default_styles() -> dict[str, ProgressStyle]:
    styles = {}

    def add(style: ProgressStyle):
        styles[style.name] = style

    add(
        ProgressStyle(
            name="emerald_glow",
            fill_char="█",
            empty_char="░",
            fill_colors=(
                _STYLE_COLOR_NAMES["emerald"],
                _STYLE_COLOR_NAMES["spring"],
            ),
            empty_color=_STYLE_COLOR_NAMES["slate"],
            gradient=True,
            head_char="█",
            head_color=_STYLE_COLOR_NAMES["mint"],
        )
    )

    add(
        ProgressStyle(
            name="sunset",
            fill_char="▉",
            empty_char="·",
            fill_colors=(
                _STYLE_COLOR_NAMES["amber"],
                _STYLE_COLOR_NAMES["peach"],
                _STYLE_COLOR_NAMES["rose"],
            ),
            empty_color=_STYLE_COLOR_NAMES["evening"],
            gradient=True,
            head_char="▉",
            head_color=_STYLE_COLOR_NAMES["carnation"],
        )
    )

    add(
        ProgressStyle(
            name="ocean",
            fill_char="▓",
            empty_char="░",
            fill_colors=(
                _STYLE_COLOR_NAMES["deep_sea"],
                _STYLE_COLOR_NAMES["aqua"],
                _STYLE_COLOR_NAMES["foam"],
            ),
            empty_color=_STYLE_COLOR_NAMES["slate"],
            gradient=True,
            head_char="▓",
            head_color=_STYLE_COLOR_NAMES["foam"],
        )
    )

    add(
        ProgressStyle(
            name="mono",
            fill_char="█",
            empty_char="-",
        )
    )

    add(
        ProgressStyle(
            name="matrix",
            fill_char="▮",
            empty_char="·",
            fill_colors=(
                _STYLE_COLOR_NAMES["emerald"],
                _STYLE_COLOR_NAMES["matrix"],
            ),
            empty_color=_STYLE_COLOR_NAMES["charcoal"],
            gradient=False,
            head_char="▮",
            head_color=_STYLE_COLOR_NAMES["lime"],
        )
    )

    return styles


_STYLE_COLOR_NAMES = {
    "emerald": _fg_rgb(47, 107, 85),
    "spring": _fg_rgb(72, 160, 120),
    "mint": _fg_rgb(152, 214, 173),
    "slate": _fg_256(240),
    "amber": _fg_256(214),
    "peach": _fg_256(217),
    "rose": _fg_256(211),
    "carnation": _fg_256(205),
    "evening": _fg_256(236),
    "deep_sea": _fg_256(24),
    "aqua": _fg_256(45),
    "foam": _fg_256(122),
    "matrix": _fg_256(34),
    "charcoal": _fg_256(237),
    "lime": _fg_256(118),
}

_PROGRESS_STYLES = _register_default_styles()
_DEFAULT_STYLE_NAME = "emerald_glow"


def progress_style_names() -> list[str]:
    return sorted(_PROGRESS_STYLES)


def get_progress_style(style: Union[str, ProgressStyle]) -> ProgressStyle:
    if isinstance(style, ProgressStyle):
        return style

    if style in _PROGRESS_STYLES:
        return _PROGRESS_STYLES[style]

    raise KeyError(f"Unknown progress style '{style}'. Available styles: {', '.join(progress_style_names())}")


def register_progress_style(style: ProgressStyle) -> None:
    _PROGRESS_STYLES[style.name] = style


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
    @classmethod
    def available_styles(cls) -> list[str]:
        return progress_style_names()

    @classmethod
    def register_style(cls, style: ProgressStyle) -> None:
        register_progress_style(style)

    @classmethod
    def set_default_style(cls, style: Union[str, ProgressStyle]) -> ProgressStyle:
        if isinstance(style, ProgressStyle):
            register_progress_style(style)
            resolved = style
        else:
            resolved = get_progress_style(style)

        global _DEFAULT_STYLE_NAME
        _DEFAULT_STYLE_NAME = resolved.name
        return resolved

    @classmethod
    def default_style(cls) -> ProgressStyle:
        return get_progress_style(_DEFAULT_STYLE_NAME)

    def __init__(self, iterable: Union[Iterable, int, dict, set], owner: Optional["LogBarType"] = None):
        self._iterating = False # state: in init or active iteration

        self._render_mode = RenderMode.AUTO

        self._title = ""
        self._subtitle = ""
        self._style = self.default_style()
        self._style_name = self._style.name
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

    def style(self, style: Union[str, ProgressStyle]):
        resolved = get_progress_style(style)
        self._style = resolved
        self._style_name = resolved.name
        return self

    def fill(self, fill: Union[str, ProgressStyle] = "█", empty: Optional[str] = None):
        if isinstance(fill, ProgressStyle) or (isinstance(fill, str) and fill in _PROGRESS_STYLES):
            return self.style(fill)

        if not isinstance(fill, str) or not fill:
            raise ValueError("fill must be a non-empty string or a named style")

        previous_style = self._style
        style = previous_style.with_fill_char(fill)

        if empty is not None:
            style = style.with_empty_char(empty)

        if previous_style.head_char is None:
            style = style.with_head_char(None)
        elif previous_style.head_char == previous_style.fill_char:
            style = style.with_head_char(fill)

        self._style = style
        self._style_name = style.name
        return self

    def colors(
        self,
        fill: Optional[Union[str, Sequence[str]]] = None,
        empty: Optional[str] = None,
        gradient: Optional[bool] = None,
        head: Optional[str] = None,
    ):
        style = self._style

        if fill is not None:
            if isinstance(fill, (list, tuple)):
                palette = tuple(_resolve_color(c) for c in fill if c)
            else:
                resolved = _resolve_color(fill)
                palette = (resolved,) if resolved else ()

            default_gradient = gradient if gradient is not None else (len(palette) > 1)
            style = style.with_colors(fill=palette, gradient=default_gradient)
        elif gradient is not None:
            style = style.with_colors(gradient=gradient)

        if empty is not None:
            style = style.with_colors(empty=_resolve_color(empty))

        if head is not None:
            style = style.with_head_char(style.head_char or style.fill_char)
            style = style.with_colors(head_color=_resolve_color(head))

        self._style = style
        self._style_name = style.name
        return self

    def head(self, char: Optional[str] = None, color: Optional[str] = None):
        style = self._style

        if char is not None:
            if char:
                style = style.with_head_char(char)
            else:
                style = style.with_head_char(None)

        if color is not None:
            style = style.with_colors(head_color=_resolve_color(color))

        self._style = style
        self._style_name = style.name
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
        empty_length = max(bar_length - filled_length, 0)
        bar_plain, bar_rendered = self._style.render(filled_length, empty_length)

        rendered_line = self._render_line(
            bar_plain=bar_plain,
            bar_rendered=bar_rendered,
            log_text=log_text,
            pre_bar_padding=padding,
            columns=columns,
        )

        self._last_rendered_line = rendered_line
        return rendered_line

    def _render_line(
        self,
        bar_plain: str,
        log_text: str,
        pre_bar_padding: str = "",
        columns: Optional[int] = None,
        bar_rendered: Optional[str] = None,
    ) -> str:
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

        plain_bar_segment = f"{bar_plain}| {log_text}"
        rendered_bar_segment = f"{bar_rendered}| {log_text}" if bar_rendered is not None else None
        append_segment(plain_bar_segment, rendered_bar_segment)

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

        period = max(self._title_animation_period, 1e-6)
        elapsed = time.time() - self._title_animation_start
        text_len = len(text)

        # pause for a few beats once the highlight reaches the end to calm flicker
        pause_steps = 5
        cycle_length = text_len + pause_steps
        cycle_step = int(elapsed / period) % cycle_length

        highlight_idx = cycle_step if cycle_step < text_len else None

        parts = [TITLE_BASE_COLOR]
        for idx, char in enumerate(text):
            if highlight_idx is not None and idx == highlight_idx:
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


class RollingProgressBar(ProgressBar):
    """Indeterminate progress indicator with a rolling highlight."""

    def __init__(self, owner: Optional["LogBarType"] = None, interval: float = 0.5, tail_length: int = 4):
        super().__init__(iterable=1, owner=owner)
        self._interval = max(0.05, float(interval))
        self._tail_length = max(1, int(tail_length))
        self._phase = 0
        self.ui_show_left_steps = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def attach(self, logger: Optional["LogBarType"] = None):
        super().attach(logger)
        self._ensure_auto_updates()
        return self

    def detach(self):
        self._stop_auto_updates()
        return super().detach()

    def close(self):
        if self.closed:
            return

        self.closed = True
        self._stop_auto_updates()
        self.detach()

    def pulse(self) -> "RollingProgressBar":
        """Advance the animation a single frame and redraw immediately."""

        self._advance_phase()
        self.draw()
        return self

    def _ensure_auto_updates(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return

        self._stop_event = threading.Event()
        thread = threading.Thread(target=self._animate_loop, name="logbar-rolling-progress", daemon=True)
        self._thread = thread
        thread.start()

    def _stop_auto_updates(self) -> None:
        thread = self._thread
        if thread is None:
            return

        self._stop_event.set()
        thread.join(timeout=max(self._interval * 2, 0.1))
        self._thread = None
        self._stop_event = threading.Event()

    def _animate_loop(self) -> None:
        while not self._stop_event.is_set() and not self.closed:
            time.sleep(self._interval)
            if self.closed:
                break
            self._advance_phase()
            try:
                self.draw()
            except Exception:
                continue

    def _advance_phase(self) -> None:
        self._phase = (self._phase + 1) % 1_000_000

    def _render_snapshot(self, columns: Optional[int] = None) -> str:
        if columns is None:
            columns, _ = terminal_size()

        elapsed_seconds = max(0, int(time.time() - self.time))
        elapsed = str(datetime.timedelta(seconds=elapsed_seconds))
        log_text = f"elapsed {elapsed}".strip()

        pre_bar_size = 0

        if self._title:
            pre_bar_size += self.max_title_len + 1
        if self._subtitle:
            pre_bar_size += self.max_subtitle_len + 1

        padding = ""

        if self._title and len(self._title) < self.max_title_len:
            padding += " " * (self.max_title_len - len(self._title))

        if self._subtitle and len(self._subtitle) < self.max_subtitle_len:
            padding += " " * (self.max_subtitle_len - len(self._subtitle))

        available_columns = columns if columns is not None and columns > 0 else 0

        bar_length = max(0, available_columns - pre_bar_size - len(log_text) - 2) if available_columns else 0
        self.bar_length = bar_length

        bar_plain, bar_rendered = self._render_animation(bar_length)

        self._last_rendered_line = self._render_line(
            bar_plain=bar_plain,
            bar_rendered=bar_rendered,
            log_text=log_text,
            pre_bar_padding=padding,
            columns=columns,
        )

        return self._last_rendered_line

    def _render_animation(self, bar_length: int) -> tuple[str, str]:
        if bar_length <= 0:
            return "", ""

        fill_char = self._style.fill_char or "█"
        empty_char = self._style.empty_char or " "
        head_char = self._style.head_char or fill_char

        tail = min(self._tail_length, bar_length)
        if tail <= 0:
            tail = 1

        width = bar_length
        phase_index = self._phase % width if width else 0

        active: dict[int, int] = {}
        for offset in range(tail):
            idx = (phase_index - offset) % width
            if idx not in active:
                active[idx] = offset

        plain_chars = [empty_char] * width
        for idx, offset in active.items():
            plain_chars[idx] = head_char if offset == 0 else fill_char

        bar_plain = ''.join(plain_chars)

        if not (self._style.fill_colors or self._style.head_color or self._style.empty_color):
            return bar_plain, bar_plain

        segments: list[str] = []
        current_color: Optional[str] = None

        for idx, char in enumerate(plain_chars):
            color = ""
            offset = active.get(idx)

            if offset is not None:
                if offset == 0 and self._style.head_color:
                    color = self._style.head_color
                else:
                    palette = self._style.fill_colors
                    if palette:
                        if self._style.gradient and len(palette) > 1:
                            palette_index = min(offset, len(palette) - 1)
                        else:
                            palette_index = idx % len(palette)
                        color = palette[palette_index]
            elif self._style.empty_color:
                color = self._style.empty_color

            if color != current_color:
                if current_color:
                    segments.append(ANSI_RESET)
                if color:
                    segments.append(color)
                current_color = color

            segments.append(char)

        if current_color:
            segments.append(ANSI_RESET)

        return bar_plain, ''.join(segments)
