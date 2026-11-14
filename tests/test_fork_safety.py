# SPDX-FileCopyrightText: 2026 ModelCloud.ai
# SPDX-License-Identifier: Apache-2.0
"""Fork safety for the shared renderer and the stdout drain thread (#77).

Every case runs in a child interpreter under a hard timeout: a regression must
fail the test instead of hanging CI. The trigger is an unbuffered stdout
(``PYTHONUNBUFFERED=1``), which makes LogBar wrap ``sys.stdout`` in
``QueueingStdout``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORK_TIMEOUT_SECONDS = 60


def _run_script(script: str, *, path=None, timeout: int = FORK_TIMEOUT_SECONDS):
    """Run a script in a child interpreter with an unbuffered stdout."""

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("LOGBAR_DISABLE_HEADLESS_DETECTION", None)
    if path is not None:
        path.write_text(textwrap.dedent(script), encoding="utf-8")
        args = [sys.executable, str(path)]
    else:
        args = [sys.executable, "-c", textwrap.dedent(script)]
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=REPO_ROOT,
    )


def test_fork_pool_logging_under_unbuffered_stdout():
    """A forked Pool worker must log instead of waiting on a dead drain thread."""

    result = _run_script(
        """
        import multiprocessing as mp

        from logbar import LogBar


        def f(i):
            LogBar.shared().info("child")
            print("child-print", flush=True)
            return i


        if __name__ == "__main__":
            LogBar.shared().info("parent")
            with mp.get_context("fork").Pool(2) as pool:
                print("map", pool.map(f, range(4)), flush=True)
        """
    )

    assert result.returncode == 0, result.stderr
    assert "map [0, 1, 2, 3]" in result.stdout


def test_fork_while_parent_thread_logs():
    """100 forks while another thread logs: every child must log and exit."""

    result = _run_script(
        """
        import os
        import threading

        from logbar import LogBar


        if __name__ == "__main__":
            stop = threading.Event()

            def log_loop():
                while not stop.is_set():
                    LogBar.shared().info("parent")

            thread = threading.Thread(target=log_loop, daemon=True)
            thread.start()
            failures = 0
            for _ in range(100):
                pid = os.fork()
                if pid == 0:
                    try:
                        LogBar.shared().info("child")
                        os._exit(0)
                    except BaseException:
                        os._exit(1)
                _, status = os.waitpid(pid, 0)
                failures += 0 if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0 else 1
            stop.set()
            thread.join(5)
            print("failures", failures, flush=True)
        """
    )

    assert result.returncode == 0, result.stderr
    assert "failures 0" in result.stdout


def test_spawn_context_logs_like_fork(tmp_path):
    """The spawn context has no inherited state and must keep working."""

    script = tmp_path / "spawn_child.py"
    result = _run_script(
        """
        import multiprocessing as mp

        from logbar import LogBar


        def f(i):
            LogBar.shared().info("spawn-child")
            return i


        if __name__ == "__main__":
            LogBar.shared().info("parent")
            with mp.get_context("spawn").Pool(2) as pool:
                print("spawn-map", pool.map(f, range(3)), flush=True)
        """,
        path=script,
    )

    assert result.returncode == 0, result.stderr
    assert "spawn-map [0, 1, 2]" in result.stdout


def test_render_lock_is_reinitialised_in_child():
    """A child must be able to take a render lock the parent held at fork."""

    result = _run_script(
        """
        import os

        from logbar import logbar as logbar_module


        if __name__ == "__main__":
            logbar_module._RENDER_LOCK.acquire()
            pid = os.fork()
            if pid == 0:
                try:
                    acquired = logbar_module._RENDER_LOCK.acquire(timeout=5)
                except BaseException:
                    os._exit(4)
                os._exit(0 if acquired else 3)
            _, status = os.waitpid(pid, 0)
            code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else status
            print("child-exit", code, flush=True)
        """
    )

    assert result.returncode == 0, result.stderr
    assert "child-exit 0" in result.stdout


def test_child_wrapper_does_not_wait_on_inherited_drain_thread():
    """A child that inherited an open wrapper must still write and flush."""

    result = _run_script(
        """
        import io
        import os
        import time

        from logbar.buffer import QueueingStdout


        if __name__ == "__main__":
            stream = io.StringIO()
            wrapper = QueueingStdout(stream)
            wrapper.write("parent")
            wrapper.flush()

            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(read_fd)
                started = time.monotonic()
                wrapper.write("child")
                wrapper.flush()
                elapsed = time.monotonic() - started
                os.write(write_fd, f"{elapsed:.3f}|{stream.getvalue()}".encode())
                os._exit(0)

            os.close(write_fd)
            _, status = os.waitpid(pid, 0)
            payload = os.read(read_fd, 4096).decode()
            os.close(read_fd)
            code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else status
            print("child", code, payload, flush=True)
        """
    )

    assert result.returncode == 0, result.stderr
    line = [row for row in result.stdout.splitlines() if row.startswith("child ")][-1]
    _, code, payload = line.split(" ", 2)
    assert code == "0", result.stdout
    elapsed, value = payload.split("|", 1)
    assert value.startswith("parent") and "child" in value, result.stdout
    assert float(elapsed) < 2.0, result.stdout
