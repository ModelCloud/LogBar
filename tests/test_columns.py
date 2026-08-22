# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import io
import re
import sys
import time
from contextlib import redirect_stdout
from unittest import mock

import pytest
from logbar import LogBar
from logbar.columns import _fit_visible
from logbar.drawing import visible_length

log = LogBar.shared()

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean(value: str) -> str:
    """Strip ANSI color and carriage-return noise from captured output."""

    cleaned = ANSI_RE.sub("", value)
    return cleaned.replace('\r', '')


def test_columns_auto_expand(capsys):
    """Grow slot widths and trailing spans as wider rows arrive."""

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
    """Reject tuple shorthand that is not part of the supported column API."""

    with pytest.raises(TypeError):
        log.columns(cols=(("name", 2), "age"))


def test_columns_simulate_updates_width_without_output():
    """Allow width probes to mutate layout without printing a row."""

    cols = log.columns(cols=("name", "details"))

    long_value = "longer than anything real"

    with mock.patch.object(cols, "_terminal_size", return_value=(80, 24)), \
         mock.patch.object(cols._logger, "_process") as mocked:
        cols.info.simulate(long_value, "ok")
        mocked.assert_not_called()

        cols.info("short", "value")

    widths = cols.widths
    assert widths
    assert widths[0] >= len(long_value)


def test_columns_support_other_levels(capsys):
    """Expose the same table helpers across debug, warn, error, and critical."""

    cols = log.columns(cols=("name", "age"))
    previous_level = log.level
    log.setLevel("DEBUG")

    buffer = io.StringIO()

    class Tee(io.TextIOBase):
        """Mirror captured output to both pytest and an in-memory buffer."""

        def write(self, data):
            """Forward writes to the real stdout and the capture buffer."""

            sys.__stdout__.write(data)
            buffer.write(data)
            return len(data)

        def flush(self):
            """Flush both mirrored output targets."""

            sys.__stdout__.flush()
            buffer.flush()

    try:
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
    finally:
        log.setLevel(previous_level)

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
    """Apply percentage hints before rendering the first header."""

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
    """Keep the old width-setter call path raising a clear error."""

    cols = log.columns(cols=("name", "age"))
    with pytest.raises(TypeError):
        cols.width("50%")


def test_columns_respects_available_width():
    """Keep the rendered table within the width budget derived from the terminal."""

    columns = 120
    with mock.patch('logbar.logbar.terminal_size', return_value=(columns, 24)):
        cols = log.columns(cols=("c1", "c2", "c3", "c4"))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cols.info.header()
            # Evaluate the level-prefix budget inside the same stdout context
            # used to render the header so the expected width matches the row.
            expected = columns - (cols._get_level_max_length() + 1)

    cleaned = _clean(buffer.getvalue())
    header_lines = [line for line in cleaned.splitlines() if '|  c1' in line]
    assert header_lines
    header_line = header_lines[0]

    row_segment = header_line[header_line.index('|'):]
    # The logger reserves one trailing space after the level prefix, so the
    # row budget is terminal width minus the prefix.
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
    """Let `fit` columns shrink to the widest observed content."""

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
    """Measure visible cell width instead of raw ANSI-decorated string length."""

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


def test_columns_fit_visible_exact_width_for_wide_chars():
    """Truncated cells with double-width characters must still match the target width."""

    text = "\u4e2d\u6587\u6d4b\u8bd5"  # four CJK chars, visible width 8
    assert visible_length(_fit_visible(text, 3)) == 3
    assert visible_length(_fit_visible(text, 4)) == 4
    assert visible_length(_fit_visible(text, 5)) == 5
    assert visible_length(_fit_visible(text, 6)) == 6
    assert _fit_visible(text, 8) == text
    assert visible_length(_fit_visible(text, 10)) == 10


def test_columns_clamp_wide_rows_to_terminal_width():
    """Do not let table rows exceed the terminal width even with very wide values."""

    columns = 80
    with mock.patch('logbar.logbar.terminal_size', return_value=(columns, 24)):
        cols = log.columns(
            "method", "layer", "name", "shape", "size", "loss", "samples",
            "damp", "avg_loss", "time", "memory", "params", "module",
            "bits", "group_size", "desc_act", "static"
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cols.info.header()
            cols.info(
                "gptq", "2", "self_attn.k_proj", "3072, 1024", "bf16: 6.8MB",
                "0.0000000399", "198077", "0.05000", "0.094", "0.372",
                "cuda 78.45G, 4.4G, 1.84G, 5.39G, 1.72G, 1.68G, 1.68G, 1.77G",
                "{'bits': 4, 'group_size': 32}",
                "model.layers.2.self_attn.k_proj", "4", "32", "True", "False"
            )

    cleaned = _clean(buffer.getvalue())
    lines = [line for line in cleaned.splitlines() if line.strip()]
    assert lines

    for line in lines:
        assert len(line) <= columns, f"line exceeds terminal width: {line!r}"

    # The rendered table content (after the log prefix) should fit the budget.
    table_lines = [line for line in lines if '|' in line]
    assert table_lines
    for line in table_lines:
        prefix_end = line.find('|')
        assert prefix_end >= 0
        assert len(line[prefix_end:]) <= (columns - prefix_end)
