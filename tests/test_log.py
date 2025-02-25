import unittest

from logbar.logbar import setup_logger

logger = setup_logger()

class TestProgressBar(unittest.TestCase):

    def test_log_simple(self):
        logger.info("hello info")

    def test_log_once(self):
        logger.info.once("hello info")
        logger.info.once("hello info")

    def test_levels(self):
        logger.info("hello info")
        logger.debug("hello debug")
        logger.warn("hello warn")
        logger.error("hello error")
        logger.critical("hello critical")