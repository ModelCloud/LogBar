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
        info_calls = 0

        with capsys.disabled():
            last_header = cols.render()
            while time.time() - start < 2.5:
                cols.info(*rows[idx % len(rows)])
                info_calls += 1
                idx += 1
                if info_calls % 5 == 0:
                    last_header = cols.render()
                time.sleep(0.2)

            last_header = cols.render()

    cols_widths = cols.widths
    assert cols_widths[0] >= len(longest_name)

    clean_header = _clean(last_header)
    raw_cells = [cell for cell in clean_header.strip().split('|') if cell]

    assert raw_cells[0].strip() == "name"
    assert raw_cells[1].strip() == "age"
    if len(raw_cells) >= 3:
        assert raw_cells[2].strip() == "school"

    assert len(raw_cells) == len(cols_widths)

    for idx, cell in enumerate(raw_cells):
        expected_len = cols_widths[idx] + (cols.padding * 2)
        assert len(cell) == expected_len
