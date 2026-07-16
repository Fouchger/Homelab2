"""Thread-local progress reporting for menu-launched operations.

The command-line interface remains deliberately quiet and machine-friendly.  The
terminal menu installs a callback while an operation is running so long-running
tools can publish their real output without knowing anything about Textual.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

ProgressCallback = Callable[[str], None]

_callback: ContextVar[ProgressCallback | None] = ContextVar("operation_progress", default=None)


def report(line: str) -> None:
    """Publish one already-sanitized progress line, when the menu requested it."""

    callback = _callback.get()
    if callback is not None:
        callback(line)


def is_enabled() -> bool:
    """Return whether the current operation has a live progress listener."""

    return _callback.get() is not None


@contextmanager
def reporting(callback: ProgressCallback) -> Iterator[None]:
    """Temporarily route operation output to ``callback`` in this worker thread."""

    token = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)
