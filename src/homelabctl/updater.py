"""Guarded, fast-forward-only control-plane source updates."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from homelabctl.proxmox_bootstrap import DiagnosticLog

DEFAULT_REPOSITORY = "Fouchger/Homelab2"
DEFAULT_BRANCH = "main"


class UpdateError(RuntimeError):
    """Raised when a safe control-plane update cannot be planned or applied."""


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    root: Path
    current_commit: str
    target_commit: str
    changed_files: tuple[str, ...]

    @property
    def up_to_date(self) -> bool:
        return self.current_commit == self.target_commit


@dataclass(frozen=True, slots=True)
class UpdateResult:
    previous_commit: str
    current_commit: str
    changed_files: tuple[str, ...]
    diagnostic_log: Path

    @property
    def updated(self) -> bool:
        return self.previous_commit != self.current_commit


def _run(
    command: list[str],
    *,
    cwd: Path,
    diagnostic: DiagnosticLog,
    accepted_codes: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    diagnostic.write("update.execute", " ".join(command))
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        diagnostic.write("update.exception", f"{type(exc).__name__}: {exc}")
        raise UpdateError(
            f"Update command could not run. Diagnostic log: {diagnostic.path}"
        ) from exc
    diagnostic.write("update.result", f"exit_code={completed.returncode}")
    for stream, content in (("stdout", completed.stdout), ("stderr", completed.stderr)):
        for line in content.splitlines():
            diagnostic.write(f"update.{stream}", line)
    if completed.returncode not in accepted_codes:
        raise UpdateError(
            f"Update safety check failed while running {command[1]}. "
            f"Diagnostic log: {diagnostic.path}"
        )
    return completed


def _tools() -> tuple[str, str]:
    git = shutil.which("git")
    uv = shutil.which("uv")
    if not git:
        raise UpdateError("Git is not installed or is not on PATH")
    if not uv:
        raise UpdateError("uv is not installed or is not on PATH")
    return git, uv


def _remote() -> tuple[str, str]:
    repository = os.environ.get("HOMELAB_REPOSITORY", DEFAULT_REPOSITORY)
    branch = os.environ.get("HOMELAB_BRANCH", DEFAULT_BRANCH)
    if not repository.replace("-", "").replace("_", "").replace("/", "").isalnum():
        raise UpdateError("HOMELAB_REPOSITORY must use owner/repository format")
    if repository.count("/") != 1 or not branch or branch.startswith("-"):
        raise UpdateError("The configured update repository or branch is invalid")
    return f"https://github.com/{repository}.git", branch


def prepare_update(root: Path) -> UpdatePlan:
    """Fetch and inspect the configured branch without changing checked-out source."""

    root = root.resolve()
    diagnostic = DiagnosticLog(root / "logs" / "control-plane-update.log")
    git, _ = _tools()
    dirty = _run(
        [git, "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        diagnostic=diagnostic,
    ).stdout.strip()
    if dirty:
        files = ", ".join(line[3:] for line in dirty.splitlines()[:8])
        raise UpdateError(
            "Tracked source changes must be committed or reverted before updating: "
            f"{files}. Runtime configuration, secrets, state, and logs are preserved."
        )
    repository_url, branch = _remote()
    _run(
        [git, "fetch", "--quiet", "--no-tags", repository_url, branch],
        cwd=root,
        diagnostic=diagnostic,
    )
    current = _run([git, "rev-parse", "HEAD"], cwd=root, diagnostic=diagnostic).stdout.strip()
    target = _run([git, "rev-parse", "FETCH_HEAD"], cwd=root, diagnostic=diagnostic).stdout.strip()
    ancestry = _run(
        [git, "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD"],
        cwd=root,
        diagnostic=diagnostic,
        accepted_codes=(0, 1),
    )
    if ancestry.returncode != 0:
        raise UpdateError(
            "The local branch has diverged from GitHub; automatic update will not overwrite it."
        )
    changed_output = _run(
        [git, "diff", "--name-only", "HEAD..FETCH_HEAD"],
        cwd=root,
        diagnostic=diagnostic,
    ).stdout
    changed = tuple(line for line in changed_output.splitlines() if line)
    return UpdatePlan(root, current, target, changed)


def apply_update(root: Path) -> UpdateResult:
    """Apply only a clean fast-forward and synchronize the locked Python environment."""

    plan = prepare_update(root)
    diagnostic = DiagnosticLog(plan.root / "logs" / "control-plane-update.log")
    git, uv = _tools()
    if plan.up_to_date:
        return UpdateResult(
            plan.current_commit, plan.target_commit, plan.changed_files, diagnostic.path
        )
    _run(
        [git, "merge", "--ff-only", "FETCH_HEAD"],
        cwd=plan.root,
        diagnostic=diagnostic,
    )
    try:
        _run(
            [uv, "sync", "--locked", "--no-dev"],
            cwd=plan.root,
            diagnostic=diagnostic,
        )
    except UpdateError as exc:
        raise UpdateError(
            "Source was updated, but dependency synchronization failed. Exit the menu and rerun "
            f"the installer. Diagnostic log: {diagnostic.path}"
        ) from exc
    return UpdateResult(
        plan.current_commit, plan.target_commit, plan.changed_files, diagnostic.path
    )
