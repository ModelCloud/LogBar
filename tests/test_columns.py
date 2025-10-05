import io
import re
import sys
import time
from contextlib import redirect_stdout
from unittest import mock

import pytest
from logbar import LogBar

log = LogBar.shared()

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean(value: str) -> str:
    cleaned = ANSI_RE.sub("", value)
    return cleaned.replace('\r', '')


def test_columns_auto_expand(capsys):
    cols = log.columns(cols=({"label": "name", "span": 2}, "age", "school"))

    longest_name = "Johhhhhhhhhhh"
    rows = [
        ("John", "Doe", "8", "Doe School"),
        (longest_name, "Na", "12", "Na School"),
        ("Jane", "Smith", "10", "Smith School", "Honors Program"),
    ]

    with mock.patch('logbar.logbar.terminal_size', return_value=(0, 0)):
        start = time.time()
        idx = 0
        last_header = ""
        info_calls = 0

        with capsys.disabled():
            last_header = cols.info.header()
            while time.time() - start < 2.5:
                cols.info(*rows[idx % len(rows)])
                info_calls += 1
                idx += 1
                if info_calls % 5 == 0:
                    last_header = cols.info.header()
                time.sleep(0.2)

            last_header = cols.info.header()

    cols_widths = cols.widths
    assert cols_widths[0] >= len(longest_name)
    assert cols_widths[1] >= len("Smith")
    assert cols_widths[3] >= len("Doe School")
    assert cols_widths[4] >= len("Honors Program")

    # last column span should have expanded to absorb the extra value in the final row
    assert cols.column_specs[-1].span >= 2

    clean_header = _clean(last_header)
    raw_cells = [cell for cell in clean_header.strip().split('|') if cell]

    specs = cols.column_specs
    assert len(raw_cells) == len(specs)

    assert raw_cells[0].strip() == "name"
    assert raw_cells[1].strip() == "age"
    assert raw_cells[2].strip() == "school"

    slot_widths = cols.widths
    start = 0
    for cell, spec in zip(raw_cells, specs):
        total_width = 0
        for offset in range(spec.span):
            idx = start + offset
            if idx >= len(slot_widths):
                break
            total_width += slot_widths[idx] + (cols.padding * 2)
            if offset < spec.span - 1:
                total_width += 1

        expected_len = total_width
        assert len(cell) == expected_len
        start += spec.span


def test_columns_reject_tuple_entries():
    with pytest.raises(TypeError):
        log.columns(cols=(("name", 2), "age"))


def test_columns_simulate_updates_width_without_output():
    cols = log.columns(cols=("name", "details"))

    long_value = "longer than anything real"

    with mock.patch.object(cols._logger, "_process") as mocked:
        cols.info.simulate(long_value, "ok")
        mocked.assert_not_called()

    cols.info("short", "value")

    widths = cols.widths
    assert widths
    assert widths[0] >= len(long_value)


def test_columns_support_other_levels(capsys):
    cols = log.columns(cols=("name", "age"))

    buffer = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, data):
            sys.__stdout__.write(data)
            buffer.write(data)
            return len(data)

        def flush(self):
            sys.__stdout__.flush()
            buffer.flush()

    with mock.patch('logbar.logbar.terminal_size', return_value=(0, 0)):
        with capsys.disabled():
            with redirect_stdout(Tee()):
                cols.debug.header()
                cols.debug("debug", "10")
                cols.warn.header()
                cols.warn("warn", "20")
                cols.error.header()
                cols.error("error", "30")
                cols.critical.header()
                cols.critical("critical", "40")

    captured = _clean(buffer.getvalue())
    lines = [line for line in captured.splitlines() if line.strip()]

    level_expectations = {
        "DEBUG": "debug",
        "WARN": "warn",
        "ERROR": "error",
        "CRIT": "critical",
    }

    for level, payload in level_expectations.items():
        assert any(level in line for line in lines), f"{level} not present in output"
        assert any(payload in line for line in lines), f"Value {payload} missing for {level}"

    # ensure each level row retains table delimiters
    for level in level_expectations:
        row_lines = [line for line in lines if level in line]
        assert row_lines, f"Expected row for {level}"
        for row in row_lines:
            if '+' in row:
                continue  # border
            assert row.count('|') >= 3, f"Row for {level} missing column separators"


def test_columns_initial_width_distribution(capsys):
    cols = log.columns(cols=({"label": "name", "span": 2, "width": "10%"}, "school"), width="50%")

    buffer = io.StringIO()

    with mock.patch('logbar.logbar.terminal_size', return_value=(100, 24)):
        with redirect_stdout(buffer):
            cols.update({"school": {"width": "40%"}})
            target = cols.width()
            cols.info.header()

    widths = cols.widths
    assert len(widths) == 3
    assert all(width >= 1 for width in widths)
    assert widths[2] >= widths[0]

    specs = cols.column_specs
    assert specs[0].width == ('percent', 0.1)
    assert specs[1].width == ('percent', 0.4)

    header_lines = [line for line in _clean(buffer.getvalue()).splitlines() if 'name' in line]
    assert header_lines
    header_len = len(header_lines[0].strip())
    assert header_len >= target * 0.8  # allow padding adjustments
    assert header_len <= 100  # should not exceed mocked terminal width


def test_columns_width_setter_removed():
    cols = log.columns(cols=("name", "age"))
    with pytest.raises(TypeError):
        cols.width("50%")


def test_columns_respects_available_width():
    columns = 120
    with mock.patch('logbar.logbar.terminal_size', return_value=(columns, 24)):
        cols = log.columns(cols=("c1", "c2", "c3", "c4"))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cols.info.header()

    cleaned = _clean(buffer.getvalue())
    header_lines = [line for line in cleaned.splitlines() if '|  c1' in line]
    assert header_lines
    header_line = header_lines[0]

    row_segment = header_line[header_line.index('|'):]
    expected = columns - (cols._level_max_length + 2)
    segment_len = len(row_segment)
    content_segment = row_segment[: row_segment.rfind('|') + 1]
    slot_widths = cols.widths
    computed_len = len(slot_widths) + 1  # separators
    for width in slot_widths:
        computed_len += (cols.padding * 2) + width
    assert len(content_segment) == computed_len
    assert segment_len == expected
    assert len(content_segment) < expected


def test_columns_fit_width_matches_content():
    cols = log.columns(cols=({"label": "tag", "width": "FiT"}, {"label": "message"}))

    with mock.patch('logbar.logbar.terminal_size', return_value=(100, 24)):
        cols.info.header()
        cols.info("ok", "short message")
        cols.info("verylongtagname", "another message")
        cols.info.header()

    widths = cols.widths
    assert widths[0] == len("verylongtagname")
    assert widths[1] == len("another message")
    assert cols.column_specs[0].width == ('fit', 0.0)


def test_columns_ignore_ansi_sequences():
    cols = log.columns(cols=("name", "status"))

    buffer = io.StringIO()
    red_fail = "\x1b[31mFAIL\x1b[0m"
    green_ready = "\x1b[32mREADY\x1b[0m"

    with mock.patch('logbar.logbar.terminal_size', return_value=(0, 0)):
        with redirect_stdout(buffer):
            cols.info.header()
            cols.info("task", red_fail)
            cols.info("task2", green_ready)
            cols.info.header()

    widths = cols.widths
    assert len(widths) >= 2
    expected_visible = max(len("status"), len("READY"))
    assert widths[1] == expected_visible
    assert widths[1] < len(red_fail)

    cleaned = _clean(buffer.getvalue())
    header_lines = [line for line in cleaned.splitlines() if 'name' in line and 'status' in line and '|' in line]
    assert header_lines
    final_header = header_lines[-1]
    first_pipe = final_header.index('|')
    row_segment = final_header[first_pipe + 1:]
    header_cells = [cell for cell in row_segment.split('|') if cell]
    assert len(header_cells) >= 2
    status_cell = header_cells[1]
    assert status_cell.strip() == "status"
    expected_cell_width = widths[1] + (cols.padding * 2)
    assert len(status_cell) == expected_cell_width

    row_lines = [line for line in cleaned.splitlines() if ('|  task' in line or '|  task2' in line)]
    assert row_lines
    assert any('FAIL' in line for line in row_lines)
    assert any('READY' in line for line in row_lines)
