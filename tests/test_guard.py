from pathlib import Path

import pytest

from homelabctl.guard import OperationLockedError, mutation_lock


def test_mutation_lock_refuses_concurrent_operation(tmp_path: Path) -> None:
    with (
        mutation_lock(tmp_path, "first operation"),
        pytest.raises(OperationLockedError, match="first operation is already running"),
        mutation_lock(tmp_path, "second operation"),
    ):
        pass


def test_mutation_lock_is_removed_after_failure(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), mutation_lock(tmp_path, "failed operation"):
        raise RuntimeError("failure")
    with mutation_lock(tmp_path, "recovery operation"):
        assert (tmp_path / ".cache" / "operations" / "mutation.lock").is_file()
