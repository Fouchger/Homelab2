from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from homelabctl.automation_ssh import (
    AutomationSshError,
    AutomationSshKey,
    ensure_automation_ssh_key,
)
from homelabctl.cli import build_parser
from homelabctl.configuration import load_config, save_config
from homelabctl.models import default_config
from homelabctl.operations import get_operation, prepare_automation_ssh

PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest guest-automation"
FINGERPRINT = "256 SHA256:example guest-automation (ED25519)"


def fake_ssh_keygen(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    if "-q" in command:
        private_key = Path(command[command.index("-f") + 1])
        private_key.write_text("PRIVATE-TEST-VALUE", encoding="utf-8")
        Path(f"{private_key}.pub").write_text(PUBLIC_KEY + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    if "-y" in command:
        return subprocess.CompletedProcess(
            command, 0, stdout="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest\n", stderr=""
        )
    if "-lf" in command:
        return subprocess.CompletedProcess(command, 0, stdout=FINGERPRINT + "\n", stderr="")
    raise AssertionError(f"Unexpected ssh-keygen command: {command}")


def test_automation_key_creation_is_idempotent_and_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = tmp_path / "homelab_ed25519"
    calls: list[list[str]] = []

    def recorded_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return fake_ssh_keygen(command, **kwargs)

    monkeypatch.setattr("homelabctl.automation_ssh.subprocess.run", recorded_run)

    created = ensure_automation_ssh_key(private_key, ssh_keygen_executable="ssh-keygen")
    reused = ensure_automation_ssh_key(private_key, ssh_keygen_executable="ssh-keygen")

    assert created == AutomationSshKey(
        private_key.resolve(),
        Path(f"{private_key.resolve()}.pub"),
        FINGERPRINT,
        True,
    )
    assert not reused.created
    assert sum("-q" in command for command in calls) == 1
    assert "PRIVATE-TEST-VALUE" not in created.fingerprint


def test_incomplete_automation_key_pair_is_never_replaced(tmp_path: Path) -> None:
    private_key = tmp_path / "homelab_ed25519"
    Path(f"{private_key}.pub").write_text(PUBLIC_KEY, encoding="utf-8")

    with pytest.raises(AutomationSshError, match="Refusing to replace an incomplete"):
        ensure_automation_ssh_key(private_key, ssh_keygen_executable="ssh-keygen")


def test_infrastructure_operation_creates_key_and_updates_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = tmp_path / "homelab_ed25519"
    public_key = Path(f"{private_key}.pub")
    config = default_config()
    config.automation.ssh_private_key = str(private_key)
    config_path = save_config(config, tmp_path / "site.yaml")
    key = AutomationSshKey(private_key, public_key, FINGERPRINT, True)
    monkeypatch.setattr(
        "homelabctl.operations.ensure_automation_ssh_key",
        lambda path: key,
    )

    result = prepare_automation_ssh(config_path)
    saved = load_config(config_path)

    assert result.succeeded
    assert saved.automation.ssh_public_key_files == [f"{private_key}.pub"]
    assert f"Fingerprint: {FINGERPRINT}" in result.lines
    assert "PRIVATE-TEST-VALUE" not in "\n".join(result.lines)


def test_infrastructure_menu_and_cli_expose_automation_key_action() -> None:
    operation = get_operation("automation-ssh")
    args = build_parser().parse_args(
        ["infrastructure", "ssh-key", "--config", "config/sites/local.yaml"]
    )

    assert operation.section == "infrastructure"
    assert operation.destructive
    assert operation.plan is not None
    assert args.infrastructure_command == "ssh-key"
