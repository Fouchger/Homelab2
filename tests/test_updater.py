from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from homelabctl.updater import UpdateError, apply_update, prepare_update

CURRENT = "a" * 40
TARGET = "b" * 40


def completed(command: list[str], stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def fake_update_command(command: list[str], **kwargs):
    action = command[1]
    if action in {"status", "fetch", "merge"} or command[0] == "uv":
        return completed(command)
    if action == "rev-parse":
        return completed(command, f"{TARGET if command[2] == 'FETCH_HEAD' else CURRENT}\n")
    if action == "merge-base":
        return completed(command)
    if action == "diff":
        return completed(command, "src/homelabctl/ui.py\nCHANGELOG.md\n")
    raise AssertionError(f"Unexpected command: {command}")


def test_update_plan_allows_ignored_runtime_files_and_lists_remote_changes(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("homelabctl.updater.shutil.which", lambda executable: executable)
    monkeypatch.setattr("homelabctl.updater.subprocess.run", fake_update_command)

    plan = prepare_update(tmp_path)

    assert plan.current_commit == CURRENT
    assert plan.target_commit == TARGET
    assert plan.changed_files == ("src/homelabctl/ui.py", "CHANGELOG.md")


def test_update_refuses_tracked_source_changes_before_fetch(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def dirty(command: list[str], **kwargs):
        commands.append(command)
        return completed(command, " M src/homelabctl/ui.py\n")

    monkeypatch.setattr("homelabctl.updater.shutil.which", lambda executable: executable)
    monkeypatch.setattr("homelabctl.updater.subprocess.run", dirty)

    with pytest.raises(UpdateError, match="Tracked source changes"):
        prepare_update(tmp_path)

    assert len(commands) == 1
    assert "--untracked-files=no" in commands[0]


def test_apply_update_uses_fast_forward_and_locked_dependency_sync(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[list[str]] = []

    def record(command: list[str], **kwargs):
        commands.append(command)
        return fake_update_command(command, **kwargs)

    monkeypatch.setattr("homelabctl.updater.shutil.which", lambda executable: executable)
    monkeypatch.setattr("homelabctl.updater.subprocess.run", record)

    result = apply_update(tmp_path)

    assert result.updated
    assert ["git", "merge", "--ff-only", "FETCH_HEAD"] in commands
    assert ["uv", "sync", "--locked", "--no-dev"] in commands
