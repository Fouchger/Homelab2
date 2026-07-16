"""Guarded installation of the control plane's Ansible prerequisites."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from homelabctl.configuration import find_project_root
from homelabctl.guard import OperationLockedError, mutation_lock


class AnsibleSetupError(RuntimeError):
    """Raised when Ansible prerequisites cannot be installed safely."""


@dataclass(frozen=True, slots=True)
class AnsibleSetupResult:
    diagnostic_log: Path
    ansible_playbook: str
    ansible_galaxy: str


def setup_plan(config_path: Path) -> tuple[str, ...]:
    root = find_project_root(config_path.parent)
    requirements = root / "ansible" / "requirements.yml"
    if not requirements.is_file():
        raise AnsibleSetupError(f"Locked Ansible requirements are missing: {requirements}")
    installed = shutil.which("ansible-playbook") and shutil.which("ansible-galaxy")
    return (
        "System package: ansible-core (Debian/Ubuntu apt repositories)",
        f"Locked collections: {requirements}",
        "Commands run with root privileges: apt-get update and apt-get install",
        "No site configuration, secrets, infrastructure, or guests will be changed",
        "Ansible executables are already present"
        if installed
        else "Ansible installation is required",
    )


def _privileged_prefix() -> list[str]:
    if os.geteuid() == 0:
        return []
    sudo = shutil.which("sudo")
    if not sudo:
        raise AnsibleSetupError("Root access or sudo is required to install ansible-core")
    return [sudo]


def _run(command: list[str], *, root: Path, diagnostic: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
    )
    with diagnostic.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n")
        handle.write(completed.stdout)
        handle.write(completed.stderr)
        handle.write(f"\nexit_code={completed.returncode}\n")
    if completed.returncode != 0:
        raise AnsibleSetupError(f"Ansible prerequisite installation failed; review {diagnostic}")


def install_ansible_prerequisites(config_path: Path) -> AnsibleSetupResult:
    root = find_project_root(config_path.parent)
    setup_plan(config_path)
    diagnostic = root / "logs" / "ansible-setup.log"
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text("Ansible prerequisite setup\n", encoding="utf-8")
    try:
        with mutation_lock(root, "Ansible prerequisite installation"):
            if not (shutil.which("ansible-playbook") and shutil.which("ansible-galaxy")):
                prefix = _privileged_prefix()
                _run([*prefix, "apt-get", "update"], root=root, diagnostic=diagnostic)
                _run(
                    [
                        *prefix,
                        "env",
                        "DEBIAN_FRONTEND=noninteractive",
                        "apt-get",
                        "install",
                        "-y",
                        "--no-install-recommends",
                        "ansible-core",
                    ],
                    root=root,
                    diagnostic=diagnostic,
                )
            galaxy = shutil.which("ansible-galaxy")
            playbook = shutil.which("ansible-playbook")
            if not galaxy or not playbook:
                raise AnsibleSetupError(
                    "ansible-core installed but its executables are unavailable"
                )
            _run(
                [
                    galaxy,
                    "collection",
                    "install",
                    "--requirements-file",
                    str(root / "ansible" / "requirements.yml"),
                ],
                root=root,
                diagnostic=diagnostic,
            )
    except (OSError, subprocess.SubprocessError, OperationLockedError) as exc:
        raise AnsibleSetupError(str(exc)) from exc
    return AnsibleSetupResult(diagnostic, playbook, galaxy)
