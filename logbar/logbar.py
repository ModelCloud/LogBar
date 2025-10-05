# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import logging
from enum import Enum
from typing import Iterable, Optional, Sequence, Union

from .terminal import terminal_size
from .columns import ColumnSpec, ColumnsPrinter

# global static/shared logger instance
logger = None
last_pb_instance = None # one for logger, 2 for progressbar
last_rendered_length = 0

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

    def columns(self, *headers, cols: Optional[Sequence] = None, width: Optional[Union[str, int, float]] = None, padding: int = 2):
        """Return a column-aware helper that keeps column widths aligned."""

        header_defs: Optional[Sequence] = None

        if cols is not None:
            if isinstance(cols, (str, bytes)):
                header_defs = [cols]
            elif isinstance(cols, Iterable):
                header_defs = list(cols)
            else:
                header_defs = [cols]
        elif headers:
            if len(headers) == 1 and isinstance(headers[0], Iterable) and not isinstance(headers[0], (str, bytes)):
                header_defs = list(headers[0])
            else:
                header_defs = list(headers)

        return ColumnsPrinter(
            logger=self,
            headers=header_defs,
            padding=padding,
            width_hint=width,
            level_enum=LEVEL,
            level_max_length=LEVEL_MAX_LENGTH,
            terminal_size_provider=lambda: terminal_size(),
        )

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

        global last_rendered_length
        columns, _ = terminal_size()
        str_msg = self._format_message(msg, args)

        line_length = len(level.value) + (LEVEL_MAX_LENGTH - len(level.value)) + 1 + len(str_msg)

        if columns > 0:
            padding_needed = max(0, columns - LEVEL_MAX_LENGTH - 2 - len(str_msg))
            str_msg += " " * padding_needed  # -2 for cursor + space between LEVEL and msg
            printable_length = columns
            last_rendered_length = printable_length
        else:
            printable_length = line_length
            if last_rendered_length > printable_length:
                str_msg += " " * (last_rendered_length - printable_length)

        global last_pb_instance
        if isinstance(last_pb_instance, ProgressBar) and not last_pb_instance.closed:
            print('\r',end='',flush=True)

        # Get the color for the log level

        reset = COLORS["RESET"]
        color = COLORS.get(level.value, reset)

        level_padding = " " * (LEVEL_MAX_LENGTH - len(level.value)) # 5 is max enum string length
        print(f"\r{color}{level.value}{reset}{level_padding} {str_msg}", end='\n', flush=True)

        if columns <= 0:
            last_rendered_length = printable_length

        if isinstance(last_pb_instance, ProgressBar):
            if not last_pb_instance.closed:
                # only do this for our instance
                if self == logger:
                    #print('\r', end='', flush=True)
                    last_pb_instance.draw()
            else:
                last_pb_instance = None
