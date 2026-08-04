# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

# adapted from github.com/onsim/shutils

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import sys
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class RenderBackendState:
    """Snapshot of the output backend capabilities for a single render pass."""

    columns: int
    lines: int
    is_tty: bool
    notebook: bool
    supports_cursor: bool
    supports_ansi: bool
    supports_styling: bool
    supports_symbols: bool = False
    headless: bool = False


def _stream_terminal_size(stream: Optional[object], fallback: tuple[int, int]) -> Optional[tuple[int, int]]:
    """Query terminal size from a specific stream when it exposes `fileno()`."""

    target = stream if stream is not None else sys.stdout
    try:
        fileno = getattr(target, "fileno", None)
    except (AttributeError, OSError, ValueError):
        return None
    if not callable(fileno):
        return None

    try:
        size = os.get_terminal_size(fileno())
    except (AttributeError, OSError, ValueError):
        return None

    return (size.columns or fallback[0], size.lines or fallback[1])

def terminal_size(fallback=(80, 24), stream: Optional[object] = None):
    """Get the size of the terminal window.

    When ``stream`` reports itself as a TTY, the active terminal is queried
    directly through its file descriptor (``os.get_terminal_size``) so that
    stale ``COLUMNS``/``LINES`` environment variables do not override a resized
    terminal. This matters for multiplexers such as tmux/screen, where the
    shell may inherit an old window size.

    If ``stream`` is not a TTY or its file descriptor cannot be queried,
    ``shutil.get_terminal_size`` is used. That helper will fall back to the
    ``COLUMNS``/``LINES`` environment variables and finally to the supplied
    fallback tuple.

    If the terminal size cannot be successfully queried, either because
    the system doesn't support querying, or because we are not
    connected to a terminal, the value given in fallback parameter
    is used. Fallback defaults to (80, 24) which is the default
    size used by many terminal emulators.
    """

    target = stream if stream is not None else sys.stdout

    isatty = getattr(target, "isatty", None)
    try:
        if callable(isatty) and not isatty():
            pass
        else:
            size = _stream_terminal_size(target, fallback)
            if size is not None:
                return (max(0, int(size[0])), max(0, int(size[1])))
    except (AttributeError, OSError, ValueError):
        pass

    columns = 0
    lines = 0
    try:
        columns = int(os.environ['COLUMNS'])
    except (KeyError, ValueError):
        pass

    try:
        lines = int(os.environ['LINES'])
    except (KeyError, ValueError):
        pass

    if columns <= 0 or lines <= 0:
        try:
            queried = shutil.get_terminal_size(fallback)
            if columns <= 0:
                columns = queried.columns or fallback[0]
            if lines <= 0:
                lines = queried.lines or fallback[1]
        except (OSError, ValueError):
            if columns <= 0:
                columns = fallback[0]
            if lines <= 0:
                lines = fallback[1]

    return (max(0, int(columns)), max(0, int(lines)))


# Environment markers used by AI-agent, remote, or non-interactive runtimes.
# A match on its own is enough to disable animated/redrawing UI in LogBar.
_HEADLESS_ENV_VARS = frozenset(
    [
        "CI",
        "CI_NAME",
        "BUILD_ID",
        "BUILDKITE",
        "TEAMCITY_VERSION",
        "TF_BUILD",
        "JENKINS_URL",
        "CIRCLECI",
        "TRAVIS",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "AGENT",
        "AI_AGENT",
        "AGENT_ID",
        "SMITHERY",
        "AIDER",
        "CODEX_HOME",
        "CODEX_SQLITE_HOME",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "CODEX_NON_INTERACTIVE",
        "DEVIN_OUTPOST_SESSION_ID",
        "DEVIN_OUTPOST_CONNECT_TOKEN",
        "DEVIN_OUTPOST_GATEWAY_URL",
        "DEVIN_REMOTE_AUTH_TOKEN",
        "DEVIN_REMOTE_STATE_DIR",
        "DEVIN_PTY_BRIDGE_PORT",
        "JPY_PARENT_PID",
        "IPYKERNEL_PARENT_PID",
        "JUPYTER_SERVER_URI",
        "KAGGLE_KERNEL_RUN_TYPE",
        "COLAB_GPU",
        "COLAB_BACKEND_VERSION",
    ]
)

# Environment variable name prefixes that strongly indicate an AI-agent shell.
_HEADLESS_ENV_PREFIXES = (
    "DEVIN_",
    "CODEX_",
    "SMITHERY_",
    "AIDER_",
    "CLAUDE_",
    "ANTHROPIC_",
    "COPILOT_",
    "__COG_",
)


def _is_stream_tty(stream: Optional[object]) -> bool:
    """Best-effort check whether ``stream`` is connected to a real terminal."""

    target = stream if stream is not None else sys.stdout
    isatty = getattr(target, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _env_flag_enabled(name: str) -> bool:
    """Return True when ``name`` is set to a non-empty, non-disabling value."""

    value = os.environ.get(name, "").strip().lower()
    return value not in {"", "0", "false", "off", "no"}


# xdist worker markers are set before test modules are imported; cache the flag
# at import time so tests that patch ``os.environ`` still detect pytest correctly.
_PYTEST_XDIST_WORKER = bool(os.environ.get("PYTEST_XDIST_WORKER"))


def _running_under_pytest() -> bool:
    """Best-effort detection for pytest-driven terminal sessions."""

    if _PYTEST_XDIST_WORKER:
        return True

    argv0 = str(sys.argv[0]).lower() if sys.argv else ""
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in argv0


def _is_headless_environment(*, notebook: bool = False) -> bool:
    """Detect non-interactive, AI-agent, notebook, or CI environments.

    Headless detection is intentionally disabled while LogBar is running under
    pytest so that the test suite can continue to assert against rendered
    output. Callers can force redrawing with ``LOGBAR_FORCE_PROGRESS=1`` or
    disable this heuristic with ``LOGBAR_DISABLE_HEADLESS_DETECTION=1``.
    """

    env = os.environ

    if env.get("LOGBAR_FORCE_PROGRESS", "").strip().lower() not in {"", "0", "false", "off", "no"}:
        return False

    if env.get("LOGBAR_DISABLE_HEADLESS_DETECTION", "").strip().lower() not in {"", "0", "false", "off", "no"}:
        return False

    # Do not disable the UI while the test suite is driving it.
    if _running_under_pytest():
        return False

    if notebook:
        return True

    if any(name in env for name in _HEADLESS_ENV_VARS):
        return True

    if any(key.startswith(_HEADLESS_ENV_PREFIXES) for key in env):
        return True

    if env.get("TERM", "").strip().lower() == "dumb":
        return True

    return False


def render_backend_state(
    *,
    stream: Optional[object] = None,
    fallback: tuple[int, int] = (80, 24),
    size_provider: Optional[Callable[[], Tuple[int, int]]] = None,
    notebook: bool = False,
) -> RenderBackendState:
    """Resolve size and capability flags for the active rendering backend."""

    target = stream if stream is not None else sys.stdout
    provider = size_provider or (lambda: terminal_size(fallback=fallback, stream=target))
    columns, lines = provider()

    is_tty = _is_stream_tty(target)

    env = os.environ
    term_value = env.get("TERM", "").strip().lower()
    force_cursor_value = env.get("LOGBAR_FORCE_TERMINAL_CURSOR", "")
    force_cursor = bool(force_cursor_value.strip())

    _disabled_values = {"", "0", "false", "off", "no"}
    force_ansi = any(
        env.get(name, "").strip().lower() not in _disabled_values
        for name in ("LOGBAR_FORCE_ANSI", "CLICOLOR_FORCE", "FORCE_COLOR")
    )
    disable_styling = (
        "NO_COLOR" in env
        or env.get("ANSI_COLORS_DISABLED", "").strip().lower() not in _disabled_values
    )
    raw_ansi_blocked = term_value == "dumb" and not force_ansi

    supports_cursor = is_tty or force_cursor
    if notebook:
        supports_cursor = False
    elif force_cursor:
        supports_cursor = True

    supports_ansi = False
    if not notebook and not disable_styling and not raw_ansi_blocked:
        supports_ansi = force_ansi or is_tty

    supports_styling = False
    if not disable_styling:
        supports_styling = notebook or force_ansi or is_tty

    headless = _is_headless_environment(notebook=notebook)

    # A headless backend should never claim cursor support. ANSI color and
    # styling are still honored when the user explicitly forces them.
    if headless:
        supports_cursor = False
        if not force_ansi:
            supports_ansi = False
            supports_styling = False
        # Notebooks always render through the notebook path and do not use
        # terminal styling/cursor state, even when a force-color flag is set.
        if notebook:
            supports_styling = False

    # Symbol prefixes require color support plus either a real TTY or an
    # explicit force flag; they are not a notebook concept.
    supports_symbols = supports_ansi and (
        _env_flag_enabled("LOGBAR_FORCE_SYMBOL_PREFIX") or _is_stream_tty(target)
    )

    return RenderBackendState(
        columns=max(0, int(columns)),
        lines=max(0, int(lines)),
        is_tty=is_tty,
        notebook=notebook,
        supports_cursor=supports_cursor,
        supports_ansi=supports_ansi,
        supports_styling=supports_styling,
        supports_symbols=supports_symbols,
        headless=headless,
    )
