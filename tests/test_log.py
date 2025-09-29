import io
from contextlib import redirect_stdout
import unittest
from unittest import mock


from logbar import LogBar

log = LogBar.shared(override_logger=True)


class TestProgressBar(unittest.TestCase):

    def capture_log(self, callable_, *args, **kwargs):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            callable_(*args, **kwargs)
        return buffer.getvalue()

    def test_log_simple(self):
        log.info("hello info")

    def test_log_once(self):
        log.info.once("hello info 1")
        log.info.once("hello info 1")

    def test_levels(self):
        log.info("hello info")
        log.debug("hello debug")
        log.warn("hello warn")
        log.error("hello error")
        log.critical("hello critical")

    def test_log_without_terminal_state(self):
        """LogBar should operate even when the runtime lacks a terminal."""

        stdout = io.StringIO()

        with mock.patch('sys.stdout', stdout), \
             mock.patch('logbar.terminal.shutil.get_terminal_size', side_effect=OSError()), \
             mock.patch.dict('logbar.terminal.os.environ', {}, clear=True):
            log.info("logging without terminal")

        # The log output should have been written to the patched stdout buffer.
        self.assertIn("logging without terminal", stdout.getvalue())

    def test_percent_formatting(self):
        output = self.capture_log(log.info, "%d", 123)
        self.assertIn("123", output)

    def test_percent_formatting_multiple_args(self):
        cases = [
            ("Numbers: %d %d %d", (1, 2, 3)),
            ("Signed and padded: %+d %05d", (42, 7)),
            ("Floats: %.2f %.1f", (3.14159, 2.5)),
            ("Mapping: %(name)s => %(value)04d", ({"name": "counter", "value": 12},)),
            ("Literal percent %% and value %d%%", (88,)),
        ]

        for fmt, args in cases:
            output = self.capture_log(log.info, fmt, *args)

            fmt_args = args
            if len(args) == 1 and isinstance(args[0], dict):
                fmt_args = args[0]

            expected = fmt % fmt_args
            self.assertIn(expected, output)
