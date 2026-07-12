from __future__ import annotations

import json
import ssl
import subprocess
import urllib.error
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

import pytest
import yaml

from homelabctl.models import default_config
from homelabctl.operations import prepare_proxmox_ssh
from homelabctl.proxmox_bootstrap import (
    PROVISIONING_PRIVILEGES,
    REMOTE_BOOTSTRAP_SCRIPT,
    DiagnosticLog,
    ProxmoxBootstrapError,
    ProxmoxTokenRecoveryRequired,
    apply_bootstrap,
    build_plan,
    ensure_bootstrap_ssh_key,
    safe_remote_diagnostics,
    verify_api_token,
)
from homelabctl.secrets import ProviderSecret, SecretBundle, SecretPlaceholderError


def test_plan_uses_configured_token_and_excludes_administrator_privileges() -> None:
    plan = build_plan(default_config())

    assert plan.ssh_target == "root@pve.home.arpa"
    assert plan.user_id == "homelab@pve"
    assert plan.token_name == "control-plane"
    assert plan.token_id == "homelab@pve!control-plane"
    assert plan.privileges == PROVISIONING_PRIVILEGES
    assert "Permissions.Modify" not in plan.privileges
    assert "Sys.Modify" not in plan.privileges
    assert "Administrator" not in plan.privileges


def test_remote_workflow_is_idempotent_and_uses_separated_token_acls() -> None:
    assert "pveum role modify" in REMOTE_BOOTSTRAP_SCRIPT
    assert "pveum user modify" in REMOTE_BOOTSTRAP_SCRIPT
    assert "-privsep 1" in REMOTE_BOOTSTRAP_SCRIPT
    assert '-token "$full_token_id"' in REMOTE_BOOTSTRAP_SCRIPT
    assert 'if [ "$token_exists" -eq 1 ] && [ "$rotate_token" -ne 1 ]' in REMOTE_BOOTSTRAP_SCRIPT
    assert "pveum user token remove" in REMOTE_BOOTSTRAP_SCRIPT
    assert 'privileges="${privileges//,/ }"' in REMOTE_BOOTSTRAP_SCRIPT
    assert "HOMELAB_BOOTSTRAP:" in REMOTE_BOOTSTRAP_SCRIPT
    assert "json_field_exists" in REMOTE_BOOTSTRAP_SCRIPT
    assert "pveum role list --output-format json" in REMOTE_BOOTSTRAP_SCRIPT
    assert "pveum user list --output-format json" in REMOTE_BOOTSTRAP_SCRIPT
    assert 'pveum user token list "$user_id" --output-format json' in REMOTE_BOOTSTRAP_SCRIPT
    assert "exists_in_first_column" not in REMOTE_BOOTSTRAP_SCRIPT


def test_new_token_is_captured_to_sops_and_verified_without_entering_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_value = "one-time-token-value"
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["ssh"], returncode=0, stdout=json.dumps({"value": token_value}), stderr=""
        )
    )
    set_token = Mock()
    verify = Mock()
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.subprocess.run", run)
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.set_proxmox_token", set_token)
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.verify_api_token", verify)

    result = apply_bootstrap(
        default_config(),
        "secrets.enc.yaml",
        ssh_executable="ssh",
        sops_executable="sops",
    )

    full_token = f"homelab@pve!control-plane={token_value}"
    assert result.created_or_rotated
    set_token.assert_called_once_with("secrets.enc.yaml", full_token, sops_executable="sops")
    verify.assert_called_once()
    assert verify.call_args.args == (default_config(), full_token)
    assert verify.call_args.kwargs["diagnostic"].path == result.diagnostic_log
    command = run.call_args.args[0]
    assert "BatchMode=yes" in command
    assert "StrictHostKeyChecking=accept-new" in command
    assert token_value not in " ".join(command)
    assert token_value not in run.call_args.kwargs["input"]


def test_existing_token_is_reconciled_without_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["ssh"], returncode=0, stdout='{"status":"existing"}', stderr=""
        )
    )
    bundle = SecretBundle(
        proxmox=ProviderSecret(api_token="homelab@pve!control-plane=stored-token-value")
    )
    set_token = Mock()
    verify = Mock()
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.subprocess.run", run)
    load = Mock(return_value=bundle)
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.load_secrets", load)
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.set_proxmox_token", set_token)
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.verify_api_token", verify)

    result = apply_bootstrap(
        default_config(),
        "secrets.enc.yaml",
        ssh_executable="ssh",
        sops_executable="sops",
    )

    assert not result.created_or_rotated
    set_token.assert_not_called()
    verify.assert_called_once()
    assert "config" not in load.call_args.kwargs
    assert "0" in run.call_args.args[0]


def test_existing_token_with_placeholder_requires_explicit_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "homelabctl.proxmox_bootstrap.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["ssh"], returncode=0, stdout='{"status":"existing"}', stderr=""
        ),
    )
    monkeypatch.setattr(
        "homelabctl.proxmox_bootstrap.load_secrets",
        Mock(side_effect=SecretPlaceholderError("generated placeholder")),
    )

    with pytest.raises(ProxmoxTokenRecoveryRequired, match="SOPS"):
        apply_bootstrap(
            default_config(),
            "secrets.enc.yaml",
            ssh_executable="ssh",
            sops_executable="sops",
        )


def test_rotation_is_explicit_in_remote_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["ssh"], returncode=0, stdout='{"value":"rotated"}', stderr=""
        )
    )
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.subprocess.run", run)
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.set_proxmox_token", Mock())
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.verify_api_token", Mock())

    apply_bootstrap(
        default_config(),
        "secrets.enc.yaml",
        rotate_token=True,
        ssh_executable="ssh",
        sops_executable="sops",
    )

    assert "1" in run.call_args.args[0]


def test_remote_failure_does_not_copy_protected_output(monkeypatch: pytest.MonkeyPatch) -> None:
    leaked = "one-time-secret-must-not-escape"
    monkeypatch.setattr(
        "homelabctl.proxmox_bootstrap.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["ssh"], returncode=1, stdout=leaked, stderr=leaked
        ),
    )

    with pytest.raises(ProxmoxBootstrapError) as captured:
        apply_bootstrap(default_config(), "secrets.enc.yaml", ssh_executable="ssh")

    assert leaked not in str(captured.value)


def test_remote_failure_reports_prefixed_diagnostics_with_secrets_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "homelab@pve!control-plane=12345678-1234-1234-1234-123456789abc"
    stderr = (
        "HOMELAB_BOOTSTRAP: ==> Creating role HomelabProvisioner\n"
        "HOMELAB_BOOTSTRAP: unknown privilege 'Example.Invalid'\n"
        f"HOMELAB_BOOTSTRAP: protected value {token}\n"
    )
    monkeypatch.setattr(
        "homelabctl.proxmox_bootstrap.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["ssh"], returncode=1, stdout='{"value":"must-stay-hidden"}', stderr=stderr
        ),
    )

    with pytest.raises(ProxmoxBootstrapError) as captured:
        apply_bootstrap(default_config(), "secrets.enc.yaml", ssh_executable="ssh")

    message = str(captured.value)
    assert "Creating role HomelabProvisioner" in message
    assert "unknown privilege 'Example.Invalid'" in message
    assert "must-stay-hidden" not in message
    assert "12345678-1234-1234-1234-123456789abc" not in message
    assert "[REDACTED]" in message


def test_diagnostic_log_keeps_safe_output_and_suppresses_token_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_value = "one-time-secret-must-not-be-logged"
    stderr = "HOMELAB_BOOTSTRAP: ==> Creating token homelab@pve!control-plane\n"
    monkeypatch.setattr(
        "homelabctl.proxmox_bootstrap.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["ssh"],
            returncode=0,
            stdout=json.dumps({"value": token_value}),
            stderr=stderr,
        ),
    )
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.set_proxmox_token", Mock())
    monkeypatch.setattr("homelabctl.proxmox_bootstrap.verify_api_token", Mock())
    log_path = tmp_path / "bootstrap.log"

    apply_bootstrap(
        default_config(),
        "secrets.enc.yaml",
        ssh_executable="ssh",
        diagnostic_log_path=log_path,
    )

    logged = log_path.read_text(encoding="utf-8")
    assert "Creating token homelab@pve!control-plane" in logged
    assert "new-token response (value suppressed)" in logged
    assert token_value not in logged


def test_api_certificate_failure_has_actionable_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verification_error = ssl.SSLCertVerificationError(1, "unable to get local issuer certificate")
    monkeypatch.setattr(
        "homelabctl.proxmox_bootstrap.urllib.request.urlopen",
        Mock(side_effect=urllib.error.URLError(verification_error)),
    )
    diagnostic = DiagnosticLog(tmp_path / "bootstrap.log")

    with pytest.raises(ProxmoxBootstrapError, match="deliberately disable"):
        verify_api_token(
            default_config(),
            "homelab@pve!control-plane=test-value",
            diagnostic=diagnostic,
        )

    logged = diagnostic.path.read_text(encoding="utf-8")
    assert "CERTIFICATE_VERIFY_FAILED" not in logged or "api.exception" in logged


def test_unprefixed_arbitrary_diagnostics_are_not_displayed() -> None:
    assert safe_remote_diagnostics("arbitrary protected output") == ()


def test_invalid_token_identifier_is_rejected_before_ssh() -> None:
    config = default_config()
    config.proxmox.token_id = "not-a-full-token-id"

    with pytest.raises(ProxmoxBootstrapError, match="user@realm!token"):
        build_plan(config)


def test_dedicated_ssh_key_creation_returns_only_public_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key = tmp_path / "proxmox_bootstrap_ed25519"
    public_value = "ssh-ed25519 AAAATEST homelab-control-plane-proxmox-bootstrap"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("-f") + 1])
        output.write_text("PRIVATE-TEST-VALUE", encoding="utf-8")
        Path(f"{output}.pub").write_text(public_value, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("homelabctl.proxmox_bootstrap.subprocess.run", fake_run)

    path, displayed, created = ensure_bootstrap_ssh_key(
        private_key, ssh_keygen_executable="ssh-keygen"
    )

    assert path == private_key
    assert displayed == public_value
    assert created
    assert "PRIVATE" not in displayed


def test_prepare_ssh_returns_copyable_ssh_copy_id_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = default_config()
    config.proxmox.api_url = "https://192.168.20.10:8006"
    config_path = tmp_path / "site.yaml"
    config_path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    private_key = PurePosixPath("/root/.ssh/proxmox_bootstrap_ed25519")
    monkeypatch.setattr(
        "homelabctl.operations.ensure_bootstrap_ssh_key",
        lambda: (private_key, "ssh-ed25519 AAAATEST comment", True),
    )

    result = prepare_proxmox_ssh(config_path)

    assert result.succeeded
    assert result.copy_text == (
        "ssh-copy-id -i /root/.ssh/proxmox_bootstrap_ed25519.pub root@192.168.20.10"
    )
    assert result.interactive_command == (
        "ssh-copy-id",
        "-i",
        "/root/.ssh/proxmox_bootstrap_ed25519.pub",
        "root@192.168.20.10",
    )
    assert result.fallback_text is not None
    assert "ssh-ed25519 AAAATEST comment" in result.fallback_text
