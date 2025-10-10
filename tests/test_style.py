import sys
import time

import pytest

from logbar import LogBar
from logbar.progress import ProgressBar

log = LogBar.shared(override_logger=True)


def _animate_style(style_name: str, capsys, duration: float = 2.0, step_delay: float = 0.1) -> None:
    pb = log.pb(range(40)).title(f"Style: {style_name}").manual()
    pb.style(style_name)
    total = len(pb)
    start = time.time()
    with capsys.disabled():
        sys.stdout.write(f"\nRendering progress style '{style_name}' for {duration:.1f}s\n")
        sys.stdout.flush()

        try:
            current = 0
            while True:
                elapsed = time.time() - start
                if elapsed >= duration:
                    break

                pb.current_iter_step = current
                pb.draw()

                current = (current + 1) % (total + 1)
                time.sleep(step_delay)
        finally:
            pb.close()
            sys.stdout.write("\n")
            sys.stdout.flush()


@pytest.mark.parametrize("style_name", ProgressBar.available_styles())
def test_progress_style_visual(style_name: str, capsys):
    _animate_style(style_name, capsys)
