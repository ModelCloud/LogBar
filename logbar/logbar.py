# Copyright 2024-2025 ModelCloud.ai
# Copyright 2024-2025 qubitium@modelcloud.ai
# Contact: qubitium@modelcloud.ai, x.com/qubitium
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
from enum import Enum
from typing import Optional, Iterable, List

from .terminal import terminal_size

# global static/shared logger instance
logger = None
last_pb_instance = None # one for logger, 2 for progressbar

def update_last_pb_instance(src) -> None:
    global last_pb_instance
    last_pb_instance = src

# ANSI color codes
COLORS = {
    "DEBUG": "\033[36m",  # Cyan
    "INFO": "\033[32m",  # Green
    "WARN": "\033[33m",  # Yellow
    "ERROR": "\033[31m",  # Red
    "CRIT": "\033[31m",  # Red
    "RESET": "\033[0m",  # Reset to default
}

class LEVEL(str, Enum):
    DEBUG = "DEBUG"
    WARN = "WARN"
    INFO = "INFO"
    ERROR = "ERROR"
    CRITICAL = "CRIT"

LEVEL_MAX_LENGTH = 5 # ERROR/DEBUG is longest at 5 chars

class LogBar(logging.Logger):
    history = set()
    history_limit = 1000

    @classmethod
    # return a shared global/singleton logger
    def shared(cls, override_logger: Optional[bool] = False):
        global logger
        if logger is not None:
            return logger

        # save logger class
        if not override_logger:
            original_logger_cls = logging.getLoggerClass()

        logging.setLoggerClass(LogBar)

        logger = logging.getLogger("logbar")

        # restore logger cls
        if not override_logger:
            logging.setLoggerClass(original_logger_cls)

        logger.propagate = False
        logger.setLevel(logging.INFO)

        # handler = logging.StreamHandler(sys.stdout)
        # handler.setFormatter(formatter)
        # handler.flush = sys.stdout.flush
        # logger.addHandler(handler)

        # clear space from previous logs
        print("", end='\n', flush=True)

        return logger


    def pb(self, iterable: Iterable):
        from logbar.progress import ProgressBar

        return ProgressBar(iterable)

    def history_add(self, msg) -> bool:
        h = hash(msg) # TODO only msg is checked not level + msg
        if h in self.history:
            return False # add failed since it already exists

        if len(self.history) > self.history_limit:
            self.history.clear()

        self.history.add(h)

        return True

    class critical_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.CRITICAL, msg, *args, **kwargs)

    class warn_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.WARN, msg, *args, **kwargs)

    class debug_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.DEBUG, msg, *args, **kwargs)

    class info_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.INFO, msg, *args, **kwargs)

    class error_cls:
        def __init__(self, logger):
            self.logger = logger

        def once(self, msg, *args, **kwargs):
            if self.logger.history_add(msg):
                self(msg, *args, **kwargs)

        def __call__(self, msg, *args, **kwargs):
            self.logger._process(LEVEL.ERROR, msg, *args, **kwargs)

    def __init__(self, name):
        super().__init__(name)
        self._warning = self.warning
        self._debug = self.debug
        self._info = self.info
        self._error = self.error
        self._critical = self.critical

        self.warn = self.warn_cls(logger=self)
        self.debug = self.debug_cls(logger=self)
        self.info = self.info_cls(logger=self)
        self.error = self.error_cls(logger=self)
        self.critical = self.critical_cls(logger=self)

    def columns(self, headers: Optional[Iterable[str]] = None, *, padding: int = 2):
        """Return a column-aware helper that keeps column widths aligned."""

        return ColumnsPrinter(logger=self, headers=headers, padding=padding)

    def _format_message(self, msg, args):
        """Format a log message while gracefully handling extra positional args."""
        if not args:
            return str(msg)

        remaining = list(args)
        parts = []

        def consume_format(fmt, available):
            if not isinstance(fmt, str):
                return str(fmt), 0

            if not available:
                return str(fmt), 0

            if len(available) == 1 and isinstance(available[0], dict):
                try:
                    return fmt % available[0], 1
                except (TypeError, ValueError, KeyError):
                    return str(fmt), 0

            for end in range(len(available), 0, -1):
                subset = tuple(available[:end])
                try:
                    return fmt % subset, end
                except (TypeError, ValueError, KeyError):
                    continue

            return str(fmt), 0

        current = msg
        while True:
            formatted, consumed = consume_format(current, remaining)
            parts.append(formatted)
            if consumed:
                remaining = remaining[consumed:]

            if not remaining:
                break

            next_candidate = remaining[0]
            if isinstance(next_candidate, str) and '%' in next_candidate:
                current = remaining.pop(0)
                continue

            break

        if remaining:
            parts.extend(str(arg) for arg in remaining)

        return " ".join(part for part in parts if part)

    def _process(self, level: LEVEL, msg, *args, **kwargs):
        from logbar.progress import ProgressBar

        columns, _ = terminal_size()
        str_msg = self._format_message(msg, args)

        if columns > 0:
            str_msg += " " * (columns - LEVEL_MAX_LENGTH - 2 - len(str_msg))  # -2 for cursor + space between LEVEL and msg

        global last_pb_instance
        if isinstance(last_pb_instance, ProgressBar) and not last_pb_instance.closed:
            print('\r',end='',flush=True)

        # Get the color for the log level

        reset = COLORS["RESET"]
        color = COLORS.get(level.value, reset)

        level_padding = " " * (LEVEL_MAX_LENGTH - len(level.value)) # 5 is max enum string length
        print(f"\r{color}{level.value}{reset}{level_padding} {str_msg}", end='\n', flush=True)

        if isinstance(last_pb_instance, ProgressBar):
            if not last_pb_instance.closed:
                # only do this for our instance
                if self == logger:
                    #print('\r', end='', flush=True)
                    last_pb_instance.draw()
            else:
                last_pb_instance = None


class ColumnsPrinter:
    """Helper that formats rows into aligned columns using `LogBar`."""

    def __init__(self, logger: LogBar, headers: Optional[Iterable[str]] = None, *, padding: int = 2):
        self._logger = logger
        self._padding = max(padding, 0)
        self._headers: List[str] = [str(h) for h in headers] if headers else []
        self._widths: List[int] = []
        if self._headers:
            self._update_widths(self._headers)

    @property
    def widths(self) -> List[int]:
        return list(self._widths)

    def render(self):
        padded_headers = list(self._headers)
        if len(self._widths) > len(padded_headers):
            padded_headers.extend([""] * (len(self._widths) - len(padded_headers)))

        self._update_widths(padded_headers)
        row = self._render(padded_headers)
        self._logger._process(LEVEL.INFO, row)
        return row

    def info(self, *values):
        texts = [str(value) for value in values]
        self._update_widths(texts)
        row = self._render(texts)
        self._logger._process(LEVEL.INFO, row)
        return row

    def _ensure_capacity(self, length: int) -> None:
        while len(self._widths) < length:
            self._widths.append(0)

    def _update_widths(self, values: Iterable[str]) -> None:
        values_list = [str(value) for value in values]
        self._ensure_capacity(len(values_list))
        for idx, value in enumerate(values_list):
            current = len(value)
            if current > self._widths[idx]:
                self._widths[idx] = current

    def _render(self, values: Iterable[str]) -> str:
        values_list = [str(value) for value in values]
        self._ensure_capacity(len(values_list))

        padded = []
        spacer = " " * self._padding if self._padding else ""

        for idx in range(len(self._widths)):
            text = values_list[idx] if idx < len(values_list) else ""
            padded.append(text.ljust(self._widths[idx]))

        rendered = ("|" + spacer).join(padded).rstrip()
        if rendered and rendered[0] != "|":
            rendered = f"|{rendered}"
        if rendered and not rendered.endswith("|"):
            rendered = f"{rendered}|"
        return rendered
