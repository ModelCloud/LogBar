import re
import time
from unittest import mock

from logbar import LogBar

log = LogBar.shared()

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean(value: str) -> str:
    cleaned = ANSI_RE.sub("", value)
    return cleaned.replace('\r', '')


def test_columns_auto_expand(capsys):
    cols = log.columns(["name", "age", "school"])

    longest_name = "Johhhhhhhhhhh"
    rows = [
        ("John", "Doe", "8", "Doe School"),
        (longest_name, "Na", "12", "Na School"),
    ]

    with mock.patch('logbar.logbar.terminal_size', return_value=(0, 0)):
        start = time.time()
        idx = 0
        last_header = ""

        with capsys.disabled():
            while time.time() - start < 5:
                last_header = cols.render()
                cols.info(*rows[idx % len(rows)])
                idx += 1
                time.sleep(0.2)

    cols_widths = cols.widths
    assert cols_widths[0] >= len(longest_name)

    clean_header = _clean(last_header)
    age_index = clean_header.find('age')
    assert age_index == cols_widths[0] + 2
