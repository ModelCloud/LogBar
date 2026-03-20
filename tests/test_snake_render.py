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


class TTYBuffer(StringIO):
    def __init__(self, mirror=None):
        super().__init__()
        self._mirror = sys.__stdout__ if mirror is None else mirror

    def isatty(self):
        return True

    def write(self, s):
        if self._mirror is not None:
            self._mirror.write(s)
        return super().write(s)

    def flush(self):
        if self._mirror is not None:
            flush = getattr(self._mirror, "flush", None)
            if callable(flush):
                flush()
        return super().flush()


class SnakeBoard:
    BORDER = "\033[38;5;240m"
    FOOD = "\033[38;5;196m"
    HEAD = "\033[38;5;46m"
    BODY = "\033[38;5;51m"
    RESET = "\033[0m"

    def __init__(self, width: int = 18, height: int = 6, initial_length: int = 5):
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
        return self.height + 2

    @property
    def render_width(self) -> int:
        return self.width + 2

    def reset(self):
        self.length = self.initial_length
        self._path_index = self.length - 1
        self.snake = list(reversed(self._path[:self.length]))
        self.food = self._food_targets[0]

    def _build_path(self):
        coords = []
        for y in range(self.height):
            xs = range(self.width) if y % 2 == 0 else range(self.width - 1, -1, -1)
            for x in xs:
                coords.append((x, y))
        return coords

    def advance(self):
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
        return self.render_lines()[row_index]

    def render_lines(self):
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
    def __init__(self, board: SnakeBoard, row_index: int):
        self.board = board
        self.row_index = row_index
        self.closed = False
        self._last_rendered_line = ""

    def _resolve_rendered_line(self, columns: int, force: bool = False, allow_repeat: bool = False):
        line = self.board.render_line(self.row_index)
        self._last_rendered_line = line
        return line


class TestSnakeRender(unittest.TestCase):
    def _run_snake_session(
        self,
        board: SnakeBoard,
        *,
        duration_seconds: float = 15.0,
        fps: int = 30,
        use_detected_terminal_size: bool = False,
        terminal_size_provider=None,
    ):
        from logbar import logbar as logbar_module

        frame_interval = 1.0 / fps
        frame_count = int(duration_seconds * fps)
        rows = [SnakeRenderable(board, idx) for idx in range(board.render_height)]
        buffer = TTYBuffer()
        columns = board.render_width
        started = time.perf_counter()
        terminal_ctx = (
            patch.object(logbar_module, "terminal_size", side_effect=terminal_size_provider)
            if terminal_size_provider is not None
            else nullcontext()
        )

        with patch.object(logbar_module, "_should_refresh_in_background", return_value=False), \
             patch.object(logbar_module, "_ensure_background_refresh_thread", return_value=None), \
             terminal_ctx:
            try:
                with redirect_stdout(buffer):
                    for row in rows:
                        logbar_module.attach_progress_bar(row)

                    if use_detected_terminal_size:
                        logbar_module.render_progress_stack()
                    else:
                        logbar_module.render_progress_stack(columns_hint=columns)

                    for frame in range(1, frame_count + 1):
                        board.advance()
                        if use_detected_terminal_size:
                            logbar_module.render_progress_stack()
                        else:
                            logbar_module.render_progress_stack(columns_hint=columns)

                        if frame % 90 == 0:
                            log.info(f"snake tick {frame}")

                        target = started + (frame * frame_interval)
                        remaining = target - time.perf_counter()
                        if remaining > 0:
                            time.sleep(remaining)
            finally:
                for row in rows:
                    logbar_module.detach_progress_bar(row)
                with redirect_stdout(buffer):
                    logbar_module.clear_progress_stack()

        elapsed = time.perf_counter() - started
        lines = extract_rendered_lines(buffer.getvalue())
        return elapsed, lines

    def test_render_stack_survives_snake_style_cli_animation(self):
        duration_seconds = 15.0
        board = SnakeBoard(width=18, height=6, initial_length=5)
        elapsed, lines = self._run_snake_session(board, duration_seconds=duration_seconds, fps=30)

        expected_frame = [strip_ansi(line) for line in board.render_lines()]
        final_frame = lines[-board.render_height:]

        self.assertEqual(final_frame, expected_frame)
        self.assertTrue(any("snake tick 90" in line for line in lines))
        self.assertTrue(any("snake tick 450" in line for line in lines))
        self.assertGreaterEqual(len(lines), board.render_height * 100)
        self.assertTrue(all(len(line) == board.render_width for line in final_frame))
        self.assertTrue(all(visible_length(line) == board.render_width for line in board.render_lines()))
        self.assertGreaterEqual(elapsed, duration_seconds)

    def test_render_stack_survives_fullscreen_detected_terminal_animation(self):
        from logbar import terminal as terminal_module

        duration_seconds = 15.0
        fullscreen_columns = 72
        fullscreen_lines = 18

        with patch.dict('logbar.terminal.os.environ', {}, clear=True), \
             patch('logbar.terminal.shutil.get_terminal_size', return_value=os.terminal_size((fullscreen_columns, fullscreen_lines))):
            detected_columns, detected_lines = terminal_module.terminal_size()
            board = SnakeBoard(
                width=max(8, detected_columns - 2),
                height=max(4, detected_lines - 2),
                initial_length=max(5, min(12, detected_columns // 4)),
            )
            elapsed, lines = self._run_snake_session(
                board,
                duration_seconds=duration_seconds,
                fps=30,
                use_detected_terminal_size=True,
                terminal_size_provider=lambda: terminal_module.terminal_size(),
            )

        expected_frame = [strip_ansi(line) for line in board.render_lines()]
        final_frame = lines[-board.render_height:]

        self.assertEqual(detected_columns, fullscreen_columns)
        self.assertEqual(detected_lines, fullscreen_lines)
        self.assertEqual(board.render_width, detected_columns)
        self.assertEqual(board.render_height, detected_lines)
        self.assertEqual(final_frame, expected_frame)
        self.assertTrue(any("snake tick 90" in line for line in lines))
        self.assertTrue(any("snake tick 450" in line for line in lines))
        self.assertGreaterEqual(len(lines), board.render_height * 100)
        self.assertTrue(all(len(line) == detected_columns for line in final_frame))
        self.assertTrue(all(visible_length(line) == detected_columns for line in board.render_lines()))
        self.assertGreaterEqual(elapsed, duration_seconds)
