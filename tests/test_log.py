import unittest
from unittest import mock

import io

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

    def test_log_without_terminal_state(self):
        """LogBar should operate even when the runtime lacks a terminal."""

        stdout = io.StringIO()

        with mock.patch('sys.stdout', stdout), \
             mock.patch('logbar.terminal.shutil.get_terminal_size', side_effect=OSError()), \
             mock.patch.dict('logbar.terminal.os.environ', {}, clear=True):
            log.info("logging without terminal")

        # The log output should have been written to the patched stdout buffer.
        self.assertIn("logging without terminal", stdout.getvalue())
