"""Dedicated SSH identity management for provisioned homelab guests."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from homelabctl.models import normalize_ssh_public_key


class AutomationSshError(RuntimeError):
    """Raised when the guest automation SSH identity is unsafe or unusable."""


@dataclass(frozen=True, slots=True)
class AutomationSshKey:
    private_key: Path
    public_key: Path
    fingerprint: str
    created: bool


def resolve_automation_ssh_key(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _run_ssh_keygen(command: list[str], *, error: str) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AutomationSshError(error) from exc
    if completed.returncode != 0:
        raise AutomationSshError(error)
    return completed


def ensure_automation_ssh_key(
    path: str | Path, *, ssh_keygen_executable: str | None = None
) -> AutomationSshKey:
    """Create or verify a dedicated, passphrase-free guest automation key pair."""

    private_key = resolve_automation_ssh_key(path)
    public_key = Path(f"{private_key}.pub")
    ssh_keygen = ssh_keygen_executable or shutil.which("ssh-keygen")
    if not ssh_keygen:
        raise AutomationSshError("ssh-keygen is not installed or is not on PATH")

    private_exists = private_key.exists()
    public_exists = public_key.exists()
    if private_exists != public_exists:
        raise AutomationSshError(
            f"Refusing to replace an incomplete automation SSH identity: {private_key}"
        )
    if private_exists and (not private_key.is_file() or not public_key.is_file()):
        raise AutomationSshError(
            f"Automation SSH identity paths must be regular files: {private_key}"
        )

    created = False
    if not private_exists:
        private_key.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            private_key.parent.chmod(0o700)
        _run_ssh_keygen(
            [
                ssh_keygen,
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "homelab-control-plane-guest-automation",
                "-f",
                str(private_key),
            ],
            error="Unable to create the guest automation SSH key",
        )
        if not private_key.is_file() or not public_key.is_file():
            raise AutomationSshError("Unable to create the guest automation SSH key")
        created = True

    if os.name != "nt":
        private_key.chmod(0o600)
        public_key.chmod(0o644)

    try:
        public_value = normalize_ssh_public_key(public_key.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AutomationSshError(
            f"Unable to validate the automation SSH public key: {public_key}"
        ) from exc

    derived = _run_ssh_keygen(
        [ssh_keygen, "-y", "-f", str(private_key)],
        error=(
            "Unable to verify the guest automation private key without a passphrase. "
            "Use a dedicated unattended automation key."
        ),
    )
    try:
        derived_value = normalize_ssh_public_key(derived.stdout)
    except ValueError as exc:
        raise AutomationSshError("ssh-keygen returned an invalid derived public key") from exc
    if derived_value.split()[:2] != public_value.split()[:2]:
        raise AutomationSshError("The automation SSH private and public keys do not match")

    fingerprint_result = _run_ssh_keygen(
        [ssh_keygen, "-lf", str(public_key), "-E", "sha256"],
        error="Unable to calculate the automation SSH public-key fingerprint",
    )
    fingerprint = fingerprint_result.stdout.strip()
    if "\n" in fingerprint or "SHA256:" not in fingerprint:
        raise AutomationSshError("ssh-keygen returned an invalid public-key fingerprint")

    return AutomationSshKey(private_key, public_key, fingerprint, created)
