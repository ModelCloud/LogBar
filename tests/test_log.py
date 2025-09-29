import io
import unittest
from contextlib import redirect_stdout

from logbar import LogBar

log = LogBar.shared(override_logger=True)


class TestProgressBar(unittest.TestCase):

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

    def test_percent_formatting(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            log.info("%d", 123)

        output = buffer.getvalue()
        self.assertIn("123", output)
