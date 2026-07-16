"""Cross-process guard for infrastructure mutations."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class OperationLockedError(RuntimeError):
    """Raised when another infrastructure mutation holds the lock."""


@contextmanager
def mutation_lock(root: Path, operation: str) -> Iterator[None]:
    lock_path = root / ".cache" / "operations" / "mutation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        detail = "another infrastructure operation is already running"
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
            if isinstance(existing.get("operation"), str):
                detail = f"{existing['operation']} is already running"
        except (OSError, ValueError, AttributeError):
            pass
        raise OperationLockedError(detail) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"operation": operation, "pid": os.getpid()}, handle)
        yield
    finally:
        lock_path.unlink(missing_ok=True)
