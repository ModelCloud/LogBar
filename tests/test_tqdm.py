# SPDX-FileCopyrightText: 2024-2025 ModelCloud.ai
# SPDX-FileCopyrightText: 2024-2025 qubitium@modelcloud.ai
# SPDX-License-Identifier: Apache-2.0
# Contact: qubitium@modelcloud.ai, x.com/qubitium

from io import StringIO

from logbar import LogBar, logging_redirect_tqdm, tqdm, trange

log = LogBar.shared(override_logger=True)


def test_tqdm_iterable():
    """``tqdm`` should iterate and expose ``n`` / ``total``."""

    items = list(range(5))
    with tqdm(items, desc="iter") as bar:
        for _ in bar:
            pass
    assert bar.n == 5
    assert bar.total == 5


def test_tqdm_manual_total():
    """Manual ``update`` should advance a total-based bar."""

    with tqdm(total=3, desc="manual") as bar:
        bar.update(1)
        bar.update(2)
    assert bar.n == 3


def test_tqdm_disable():
    """A disabled bar should not render and iteration still works."""

    with tqdm(range(3), disable=True) as bar:
        for _ in bar:
            pass
    assert bar.n == 3


def test_trange():
    """``trange`` should behave like ``tqdm(range(...))``."""

    with trange(4) as bar:
        for _ in bar:
            pass
    assert bar.n == 4
    assert bar.total == 4


def test_tqdm_set_description_and_postfix():
    """``set_description`` and ``set_postfix`` should update the bar state."""

    with tqdm(range(2), desc="initial") as bar:
        bar.set_description("updated")
        bar.set_postfix(loss=0.1)
        for _ in bar:
            pass
    assert bar.n == 2


def test_tqdm_write():
    """``tqdm.write`` should write to the supplied file."""

    stream = StringIO()
    tqdm.write("hello", file=stream)
    assert stream.getvalue() == "hello\n"


def test_logging_redirect_tqdm():
    """``logging_redirect_tqdm`` should be a no-op context manager."""

    with logging_redirect_tqdm():
        log.info("inside redirect")
