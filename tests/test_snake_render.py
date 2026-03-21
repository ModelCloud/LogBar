# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

import os
import re
import sys
import time
import unittest
from contextlib import nullcontext, redirect_stdout
from io import StringIO
from unittest.mock import patch

from logbar import LogBar
from logbar.drawing import strip_ansi, visible_length


log = LogBar.shared(override_logger=True)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def extract_rendered_lines(buffer: str):
    """Split captured terminal output into visible lines without ANSI escapes."""

    cleaned = ANSI_ESCAPE_RE.sub('', buffer)
    lines = []
    accumulator = []

    for char in cleaned:
        if char == '\r':
            if accumulator:
                lines.append(''.join(accumulator))
                accumulator = []
        elif char == '\n':
            if accumulator:
                lines.append(''.join(accumulator))
                accumulator = []
        else:
            accumulator.append(char)

    if accumulator:
        lines.append(''.join(accumulator))

    return [line for line in lines if line]


def replay_terminal_screen(buffer: str, screen_height: int | None = None):
    """Replay a subset of cursor-control output into visible terminal rows."""

    rows = {}
    row = 0
    col = 0
    index = 0

    def ensure_row(target_row: int):
        """Materialize sparse row storage on first write."""

        return rows.setdefault(target_row, [])

    def write_char(char: str):
        """Write one printable character at the current cursor position."""

        nonlocal col
        line = ensure_row(row)
        if col > len(line):
            line.extend(' ' * (col - len(line)))
        if col == len(line):
            line.append(char)
        else:
            line[col] = char
        col += 1

    def clamp_height():
        """Mimic viewport scrolling when the emulated screen has a height limit."""

        nonlocal row
        if screen_height is None or not rows:
            return

        min_row = min(rows)
        max_row = max(rows)
        while max_row - min_row + 1 > screen_height:
            shifted = {}
            for key, value in rows.items():
                if key != min_row:
                    shifted[key - 1] = value
            rows.clear()
            rows.update(shifted)
            row -= 1
            if not rows:
                break
            min_row = min(rows)
            max_row = max(rows)

    def erase_display(mode: int):
        """Handle the CSI J variants used by the renderer."""

        if mode == 2:
            rows.clear()
            return

        if mode != 0:
            return

        current = rows.get(row)
        if current is not None:
            del current[col:]

        for key in list(rows.keys()):
            if key > row:
                del rows[key]

    def erase_line(mode: int):
        """Handle the CSI K variants used by the renderer."""

        line = ensure_row(row)
        if mode == 2:
            rows[row] = []
            return
        if mode == 0:
            del line[col:]
            return
        if mode == 1:
            limit = min(col + 1, len(line))
            for idx in range(limit):
                line[idx] = ' '

    def insert_lines(count: int):
        """Insert blank lines at the cursor and push later rows downward."""

        if count <= 0:
            return
        shifted = {}
        for key in sorted(rows.keys(), reverse=True):
            if key >= row:
                shifted[key + count] = rows.pop(key)
        rows.update(shifted)
        clamp_height()

    def delete_lines(count: int):
        """Delete lines at the cursor and pull later rows upward."""

        if count <= 0:
            return
        for _ in range(count):
            rows.pop(row, None)
            shifted = {}
            for key in sorted(rows.keys()):
                if key > row:
                    shifted[key - 1] = rows.pop(key)
            rows.update(shifted)

    def scroll_up(count: int):
        """Scroll the sparse screen upward by removing top rows."""

        if count <= 0 or not rows:
            return
        shifted = {}
        for key, value in rows.items():
            shifted[key - count] = value
        rows.clear()
        rows.update(shifted)
        clamp_height()

    def parse_count(params: str, default: int = 1) -> int:
        """Parse the leading numeric argument from a CSI parameter list."""

        head = params.lstrip('?').split(';', 1)[0]
        return int(head) if head else default

    while index < len(buffer):
        char = buffer[index]
        if char == '\x1b' and index + 1 < len(buffer) and buffer[index + 1] == '[':
            end = index + 2
            while end < len(buffer) and not ('@' <= buffer[end] <= '~'):
                end += 1

            if end >= len(buffer):
                break

            params = buffer[index + 2:end]
            command = buffer[end]

            if command == 'A':
                row -= parse_count(params)
            elif command == 'B':
                row += parse_count(params)
            elif command == 'C':
                col += parse_count(params)
            elif command == 'D':
                col = max(0, col - parse_count(params))
            elif command == 'G':
                col = max(0, parse_count(params, default=1) - 1)
            elif command == 'J':
                erase_display(parse_count(params, default=0))
            elif command == 'K':
                erase_line(parse_count(params, default=0))
            elif command == 'L':
                insert_lines(parse_count(params))
            elif command == 'M':
                delete_lines(parse_count(params))
            elif command == 'S':
                scroll_up(parse_count(params))

            index = end + 1
            continue

        if char == '\r':
            col = 0
        elif char == '\n':
            row += 1
            clamp_height()
        else:
            write_char(char)
        index += 1

    return [''.join(rows[key]) for key in sorted(rows) if ''.join(rows[key])]


class TTYBuffer(StringIO):
    """TTY-like capture buffer that can optionally mirror output live."""

    def __init__(self, mirror=None):
        """Capture writes while optionally teeing them to a real stream."""

        super().__init__()
        self._mirror = sys.__stdout__ if mirror is None else mirror

    def isatty(self):
        """Pretend to be a TTY so cursor-based rendering stays enabled."""

        return True

    def write(self, s):
        """Mirror writes before storing them in the in-memory capture buffer."""

        if self._mirror is not None:
            self._mirror.write(s)
        return super().write(s)

    def flush(self):
        """Flush both the mirrored stream and the in-memory buffer."""

        if self._mirror is not None:
            flush = getattr(self._mirror, "flush", None)
            if callable(flush):
                flush()
        return super().flush()


class TerminalCellScreen:
    """Fixed-size cell emulator for step-by-step screen cleanliness checks."""

    def __init__(self, width: int, height: int):
        """Initialize an empty terminal grid and cursor state."""

        self.width = width
        self.height = height
        self.rows = [[' '] * width for _ in range(height)]
        self.row = 0
        self.col = 0
        self.wrap_pending = False

    def snapshot(self):
        """Return the current screen contents as plain strings."""

        return [''.join(row) for row in self.rows]

    def _clamp_cursor(self):
        """Keep the cursor inside the bounds of the emulated screen."""

        self.row = max(0, min(self.height - 1, self.row))
        self.col = max(0, min(self.width - 1, self.col))

    def _advance_line(self):
        """Advance to the next row, scrolling when already on the last row."""

        if self.row >= self.height - 1:
            self.rows.pop(0)
            self.rows.append([' '] * self.width)
            self.row = self.height - 1
        else:
            self.row += 1

    def _write_char(self, char: str):
        """Write one printable character with terminal-style line wrapping."""

        if self.width <= 0 or self.height <= 0:
            return

        if self.wrap_pending:
            self._advance_line()
            self.col = 0
            self.wrap_pending = False

        self.rows[self.row][self.col] = char
        if self.col >= self.width - 1:
            self.wrap_pending = True
        else:
            self.col += 1

    def _erase_display(self, mode: int):
        """Handle the CSI J erase-display sequences used by the renderer."""

        if mode == 2:
            self.rows = [[' '] * self.width for _ in range(self.height)]
            return

        if mode != 0:
            return

        for idx in range(self.col, self.width):
            self.rows[self.row][idx] = ' '
        for row_idx in range(self.row + 1, self.height):
            self.rows[row_idx] = [' '] * self.width

    def _erase_line(self, mode: int):
        """Handle the CSI K erase-line sequences used by the renderer."""

        if mode == 2:
            self.rows[self.row] = [' '] * self.width
            return
        if mode == 0:
            for idx in range(self.col, self.width):
                self.rows[self.row][idx] = ' '
            return
        if mode == 1:
            for idx in range(0, min(self.col + 1, self.width)):
                self.rows[self.row][idx] = ' '

    def _insert_lines(self, count: int):
        """Insert blank rows at the cursor position."""

        for _ in range(max(0, count)):
            self.rows.insert(self.row, [' '] * self.width)
            self.rows.pop()

    def _delete_lines(self, count: int):
        """Delete rows at the cursor position and pull later rows upward."""

        for _ in range(max(0, count)):
            self.rows.pop(self.row)
            self.rows.append([' '] * self.width)

    def _scroll_up(self, count: int):
        """Scroll the whole screen upward by the requested row count."""

        for _ in range(max(0, count)):
            self.rows.pop(0)
            self.rows.append([' '] * self.width)

    def _parse_count(self, params: str, default: int = 1) -> int:
        """Parse the leading numeric argument from a CSI parameter list."""

        head = params.lstrip('?').split(';', 1)[0]
        return int(head) if head else default

    def apply(self, buffer: str):
        """Replay terminal escape sequences into the fixed-size cell buffer."""

        index = 0
        while index < len(buffer):
            char = buffer[index]
            if char == '\x1b' and index + 1 < len(buffer) and buffer[index + 1] == '[':
                end = index + 2
                while end < len(buffer) and not ('@' <= buffer[end] <= '~'):
                    end += 1

                if end >= len(buffer):
                    break

                params = buffer[index + 2:end]
                command = buffer[end]
                self.wrap_pending = False

                if command == 'A':
                    self.row -= self._parse_count(params)
                elif command == 'B':
                    self.row += self._parse_count(params)
                elif command == 'C':
                    self.col += self._parse_count(params)
                elif command == 'D':
                    self.col -= self._parse_count(params)
                elif command == 'G':
                    self.col = self._parse_count(params, default=1) - 1
                elif command == 'J':
                    self._erase_display(self._parse_count(params, default=0))
                elif command == 'K':
                    self._erase_line(self._parse_count(params, default=0))
                elif command == 'L':
                    self._insert_lines(self._parse_count(params))
                elif command == 'M':
                    self._delete_lines(self._parse_count(params))
                elif command == 'S':
                    self._scroll_up(self._parse_count(params))

                self._clamp_cursor()
                index = end + 1
                continue

            if char == '\r':
                self.col = 0
                self.wrap_pending = False
            elif char == '\n':
                self._advance_line()
                self.wrap_pending = False
            else:
                self._write_char(char)
            index += 1


class SnakeBoard:
    """Deterministic snake board used as a high-motion renderer workload."""

    BORDER = "\033[38;5;240m"
    FOOD = "\033[38;5;196m"
    HEAD = "\033[38;5;46m"
    BODY = "\033[38;5;51m"
    RESET = "\033[0m"

    def __init__(self, width: int = 18, height: int = 6, initial_length: int = 5):
        """Build a deterministic board and pre-seeded food positions."""

        self.width = width
        self.height = height
        self.initial_length = max(2, min(initial_length, width * height))
        self._path = self._build_path()
        self._food_index = 0
        self._food_targets = [
            self._path[self.initial_length + 2],
            self._path[self.initial_length + 9],
            self._path[self.initial_length + 17],
        ]
        self.reset()

    @property
    def render_height(self) -> int:
        """Return the rendered height including the border rows."""

        return self.height + 2

    @property
    def render_width(self) -> int:
        """Return the rendered width including the border columns."""

        return self.width + 2

    def reset(self):
        """Reset snake position, length, and food to the initial state."""

        self.length = self.initial_length
        self._path_index = self.length - 1
        self.snake = list(reversed(self._path[:self.length]))
        self.food = self._food_targets[0]

    def _build_path(self):
        """Generate a serpentine traversal so movement is deterministic."""

        coords = []
        for y in range(self.height):
            xs = range(self.width) if y % 2 == 0 else range(self.width - 1, -1, -1)
            for x in xs:
                coords.append((x, y))
        return coords

    def advance(self):
        """Move the snake one step and grow when it reaches food."""

        self._path_index = (self._path_index + 1) % len(self._path)
        head = self._path[self._path_index]
        self.snake.insert(0, head)

        grew = False
        if head == self.food:
            self.length = min(self.length + 2, len(self._path))
            grew = True

        del self.snake[self.length:]

        if grew and self._food_index + 1 < len(self._food_targets):
            self._food_index += 1
            self.food = self._food_targets[self._food_index]

    def render_line(self, row_index: int) -> str:
        """Render one visible row of the board."""

        return self.render_lines()[row_index]

    def render_lines(self):
        """Render the full bordered board with ANSI-colored snake segments."""

        top = f"{self.BORDER}+" + "-" * self.width + f"+{self.RESET}"
        bottom = f"{self.BORDER}+" + "-" * self.width + f"+{self.RESET}"

        body_cells = set(self.snake[1:])
        head = self.snake[0]

        rows = [top]
        for y in range(self.height):
            cells = []
            for x in range(self.width):
                point = (x, y)
                if point == head:
                    cells.append(f"{self.HEAD}@{self.RESET}")
                elif point in body_cells:
                    cells.append(f"{self.BODY}o{self.RESET}")
                elif point == self.food:
                    cells.append(f"{self.FOOD}*{self.RESET}")
                else:
                    cells.append(" ")
            rows.append(f"{self.BORDER}|{self.RESET}{''.join(cells)}{self.BORDER}|{self.RESET}")
        rows.append(bottom)
        return rows


class SnakeRenderable:
    """Single-row renderable wrapper so the board participates in stack diffing."""

    def __init__(self, board: SnakeBoard, row_index: int):
        """Bind one visible row of the board to the shared render interface."""

        self.board = board
        self.row_index = row_index
        self.closed = False
        self._last_rendered_line = ""

    def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
        """Expose one board row through the same contract as progress bars."""

        line = self.board.render_line(self.row_index)
        self._last_rendered_line = line
        return line


class TestSnakeRender(unittest.TestCase):
    """Stress tests for stacked renderer correctness under animation."""

    def _run_snake_session(
        self,
        board: SnakeBoard,
        *,
        duration_seconds: float = 15.0,
        fps: int = 30,
        log_every_frames: int = 90,
        use_detected_terminal_size: bool = False,
        terminal_size_provider=None,
        output_observer=None,
    ):
        """Run a timed snake animation session and return elapsed time and raw output."""

        from logbar import logbar as logbar_module

        frame_interval = 1.0 / fps
        frame_count = int(duration_seconds * fps)
        rows = [SnakeRenderable(board, idx) for idx in range(board.render_height)]
        buffer = TTYBuffer()
        columns = board.render_width
        started = time.perf_counter()
        active_raw = ""
        last_output_len = 0
        terminal_ctx = (
            patch.object(logbar_module, "terminal_size", side_effect=terminal_size_provider)
            if terminal_size_provider is not None
            else nullcontext()
        )

        def observe(event: str, frame: int):
            """Send each newly rendered output delta to an optional observer."""

            nonlocal last_output_len
            if output_observer is None:
                return
            current = buffer.getvalue()
            delta = current[last_output_len:]
            last_output_len = len(current)
            output_observer(delta=delta, event=event, frame=frame)

        with patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
             patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
             terminal_ctx:
            try:
                with redirect_stdout(buffer):
                    for row in rows:
                        logbar_module.attach_progress_bar(row)

                    # Prime the stack once so later iterations exercise the
                    # diff renderer instead of only first-frame setup logic.
                    if use_detected_terminal_size:
                        logbar_module.render_progress_stack()
                    else:
                        logbar_module.render_progress_stack(columns_hint=columns)
                    observe("initial", 0)

                    for frame in range(1, frame_count + 1):
                        board.advance()
                        if use_detected_terminal_size:
                            logbar_module.render_progress_stack()
                        else:
                            logbar_module.render_progress_stack(columns_hint=columns)
                        observe("frame", frame)

                        # Interleave logs with animation so the test covers the
                        # log-above-stack path and the redraw invalidation path.
                        if log_every_frames > 0 and frame % log_every_frames == 0:
                            log.info(f"snake tick {frame}")
                            observe("log", frame)

                        target = started + (frame * frame_interval)
                        remaining = target - time.perf_counter()
                        if remaining > 0:
                            time.sleep(remaining)
                active_raw = buffer.getvalue()
            finally:
                for row in rows:
                    logbar_module.detach_progress_bar(row)
                with redirect_stdout(buffer):
                    logbar_module.clear_progress_stack()

        elapsed = time.perf_counter() - started
        return elapsed, active_raw

    def test_render_stack_survives_snake_style_cli_animation(self):
        """Keep the final fixed-size snake frame correct after a long animation run."""

        duration_seconds = 15.0
        board = SnakeBoard(width=18, height=6, initial_length=5)
        elapsed, raw = self._run_snake_session(board, duration_seconds=duration_seconds, fps=30)

        lines = extract_rendered_lines(raw)
        screen = replay_terminal_screen(raw, screen_height=board.render_height)
        expected_frame = [strip_ansi(line) for line in board.render_lines()]
        final_frame = screen[-board.render_height:]

        self.assertEqual(final_frame, expected_frame)
        self.assertTrue(any("snake tick 90" in line for line in lines))
        self.assertTrue(any("snake tick 450" in line for line in lines))
        self.assertTrue(all(len(line) == board.render_width for line in final_frame))
        self.assertTrue(all(visible_length(line) == board.render_width for line in board.render_lines()))
        self.assertGreaterEqual(elapsed, duration_seconds)

    def test_render_stack_survives_fullscreen_detected_terminal_animation(self):
        """Fill the detected terminal size and finish with a valid fullscreen frame."""

        from logbar import terminal as terminal_module

        duration_seconds = 15.0
        actual_size = os.terminal_size(terminal_module.terminal_size())
        fullscreen_columns = max(20, actual_size.columns)
        fullscreen_lines = max(8, actual_size.lines)

        with patch.dict('logbar.terminal.os.environ', {}, clear=True), \
             patch('logbar.terminal.shutil.get_terminal_size', return_value=os.terminal_size((fullscreen_columns, fullscreen_lines))):
            detected_columns, detected_lines = terminal_module.terminal_size()
            board = SnakeBoard(
                width=max(8, detected_columns - 2),
                height=max(4, detected_lines - 2),
                initial_length=max(5, min(12, detected_columns // 4)),
            )
            elapsed, raw = self._run_snake_session(
                board,
                duration_seconds=duration_seconds,
                fps=30,
                use_detected_terminal_size=True,
                terminal_size_provider=lambda: terminal_module.terminal_size(),
            )

        lines = extract_rendered_lines(raw)
        screen = replay_terminal_screen(raw, screen_height=board.render_height)
        expected_frame = [strip_ansi(line) for line in board.render_lines()]
        final_frame = screen[-board.render_height:]

        self.assertEqual(detected_columns, fullscreen_columns)
        self.assertEqual(detected_lines, fullscreen_lines)
        self.assertEqual(board.render_width, detected_columns)
        self.assertEqual(board.render_height, detected_lines)
        self.assertNotIn("\033[1S", raw)
        self.assertEqual(len(final_frame), board.render_height)
        self.assertEqual(final_frame[-1], expected_frame[-1])
        self.assertTrue(
            all(
                line in {expected_frame[0], expected_frame[-1]}
                or (line.startswith('|') and line.endswith('|'))
                for line in final_frame
            )
        )
        self.assertTrue(any('@' in line for line in final_frame))
        self.assertTrue(any('o' in line for line in final_frame))
        self.assertTrue(all(visible_length(line) == detected_columns for line in final_frame))
        self.assertTrue(all(visible_length(line) == detected_columns for line in board.render_lines()))
        self.assertGreaterEqual(elapsed, duration_seconds)

    def test_fullscreen_snake_keeps_screen_cells_clean_after_every_draw(self):
        """Verify every fullscreen redraw leaves no stale cells behind."""

        columns = 22
        lines = 8
        duration_seconds = 2.0
        fps = 15
        board = SnakeBoard(width=columns - 2, height=lines - 2, initial_length=5)
        screen = TerminalCellScreen(width=columns, height=lines)

        def observe(delta: str, event: str, frame: int):
            """Replay each emitted delta and assert the full screen stays clean."""

            if not delta:
                return
            self.assertNotIn("\033[1S", delta)
            screen.apply(delta)
            expected = [strip_ansi(line) for line in board.render_lines()]
            self.assertEqual(
                screen.snapshot(),
                expected,
                msg=f"screen mismatch after {event} at frame {frame}",
            )

        elapsed, _raw = self._run_snake_session(
            board,
            duration_seconds=duration_seconds,
            fps=fps,
            log_every_frames=3,
            use_detected_terminal_size=True,
            terminal_size_provider=lambda: (columns, lines),
            output_observer=observe,
        )

        self.assertGreaterEqual(elapsed, duration_seconds)
