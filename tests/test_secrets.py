from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from homelabctl.cli import main
from homelabctl.configuration import save_config
from homelabctl.models import HomelabConfig, default_config
from homelabctl.secrets import (
    SecretError,
    ensure_age_identity,
    initialize_secret_file,
    load_secrets,
    resolve_secrets_path,
    set_cloudflare_token,
    set_proxmox_token,
    validate_provider_secret,
)

TOKEN = "test-proxmox-token-secret"
CLOUDFLARE_TOKEN = "test-cloudflare-token-secret"


def encrypted_document(*, cloudflare: bool = True) -> str:
    document: dict[str, object] = {
        "schema_version": 1,
        "proxmox": {"api_token": "ENC[AES256_GCM,data:test-proxmox]"},
        "sops": {"mac": "ENC[AES256_GCM,data:test-mac]"},
    }
    if cloudflare:
        document["cloudflare"] = {"api_token": "ENC[AES256_GCM,data:test-cloudflare]"}
    return yaml.safe_dump(document, sort_keys=False)


def decrypted_document(*, cloudflare: bool = True) -> str:
    document: dict[str, object] = {
        "schema_version": 1,
        "proxmox": {"api_token": TOKEN},
    }
    if cloudflare:
        document["cloudflare"] = {"api_token": CLOUDFLARE_TOKEN}
    return yaml.safe_dump(document, sort_keys=False)


def write_encrypted_file(path: Path, *, cloudflare: bool = True) -> Path:
    path.write_text(encrypted_document(cloudflare=cloudflare), encoding="utf-8")
    return path


def completed_decryption(*, cloudflare: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["sops", "decrypt"], returncode=0, stdout=decrypted_document(cloudflare=cloudflare)
    )


def test_loads_provider_environment_without_exposing_secret_in_representation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run", lambda *args, **kwargs: completed_decryption()
    )
    bundle = load_secrets(path, sops_executable="sops")

    assert bundle.provider_environment() == {
        "PROXMOX_VE_API_TOKEN": TOKEN,
        "CLOUDFLARE_API_TOKEN": CLOUDFLARE_TOKEN,
    }
    assert TOKEN not in repr(bundle)
    assert CLOUDFLARE_TOKEN not in str(bundle)


def test_plaintext_secret_file_is_refused_before_sops_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "plaintext.yaml"
    path.write_text(decrypted_document(), encoding="utf-8")
    run = Mock()
    monkeypatch.setattr("homelabctl.secrets.subprocess.run", run)

    with pytest.raises(SecretError, match="Refusing to load plaintext"):
        load_secrets(path, sops_executable="sops")

    run.assert_not_called()


def test_sops_metadata_cannot_hide_a_plaintext_token(tmp_path: Path) -> None:
    path = tmp_path / "mixed.yaml"
    document = yaml.safe_load(encrypted_document())
    document["proxmox"]["api_token"] = TOKEN
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(SecretError, match="unencrypted or missing proxmox.api_token"):
        load_secrets(path, sops_executable="sops")


def test_decryption_failure_does_not_copy_process_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    process_secret = "must-not-appear-in-error"
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["sops"], returncode=1, stdout=process_secret, stderr=process_secret
        ),
    )

    with pytest.raises(SecretError) as captured:
        load_secrets(path, sops_executable="sops")

    assert process_secret not in str(captured.value)


def test_validation_failure_omits_invalid_secret_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    invalid = yaml.safe_dump(
        {
            "schema_version": 1,
            "proxmox": {"api_token": TOKEN},
            "unexpected": "must-not-appear-in-validation-error",
        }
    )
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["sops"], returncode=0, stdout=invalid
        ),
    )

    with pytest.raises(SecretError) as captured:
        load_secrets(path, sops_executable="sops")

    assert "must-not-appear-in-validation-error" not in str(captured.value)
    assert "unexpected" in str(captured.value)


def test_cloudflare_token_is_required_when_domains_are_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml", cloudflare=False)
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run",
        lambda *args, **kwargs: completed_decryption(cloudflare=False),
    )
    data = default_config().model_dump(mode="json")
    data["cloudflare"]["domains"] = ["example.com"]
    config = HomelabConfig.model_validate(data)

    with pytest.raises(SecretError, match="must include cloudflare.api_token"):
        load_secrets(path, config=config, sops_executable="sops")


def test_initialize_encrypts_template_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secrets" / "local.enc.yaml"
    encrypted = encrypted_document()
    run = Mock(
        return_value=subprocess.CompletedProcess(args=["sops"], returncode=0, stdout=encrypted)
    )
    monkeypatch.setattr("homelabctl.secrets.subprocess.run", run)

    created = initialize_secret_file(
        path,
        age_recipient="age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq",
        sops_executable="sops",
    )

    assert created == path
    assert path.read_text(encoding="utf-8") == encrypted
    assert TOKEN not in path.read_text(encoding="utf-8")
    assert "replace-with-proxmox-api-token-secret" in run.call_args.kwargs["input"]


def test_secret_path_can_be_selected_with_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "selected.enc.yaml"
    monkeypatch.setenv("HOMELAB_SECRETS", str(selected))

    assert resolve_secrets_path() == selected.resolve()


def test_cli_check_reports_providers_without_printing_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = save_config(default_config(), tmp_path / "site.yaml")
    secret_path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run", lambda *args, **kwargs: completed_decryption()
    )
    monkeypatch.setattr("homelabctl.secrets.shutil.which", lambda name: "sops")

    exit_code = main(
        [
            "secrets",
            "check",
            "--config",
            str(config_path),
            "--secrets",
            str(secret_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Proxmox" in output
    assert "Cloudflare" in output
    assert TOKEN not in output
    assert CLOUDFLARE_TOKEN not in output


def test_generated_placeholders_are_not_accepted_as_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["sops"],
            returncode=0,
            stdout=yaml.safe_dump(
                {
                    "schema_version": 1,
                    "proxmox": {"api_token": "replace-with-proxmox-api-token-secret"},
                }
            ),
        ),
    )

    with pytest.raises(SecretError, match="generated placeholder"):
        load_secrets(path, sops_executable="sops")


def test_proxmox_token_update_uses_stdin_not_command_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    api_token = "homelab@pve!control-plane=one-time-token-value"
    run = Mock(return_value=subprocess.CompletedProcess(args=["sops"], returncode=0, stdout=""))
    monkeypatch.setattr("homelabctl.secrets.subprocess.run", run)

    set_proxmox_token(path, api_token, sops_executable="sops")

    command = run.call_args.args[0]
    assert api_token not in command
    assert run.call_args.kwargs["input"] == json.dumps(api_token)


def test_cloudflare_token_update_uses_stdin_and_can_create_provider_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml", cloudflare=False)
    api_token = "scoped-cloudflare-token"
    run = Mock(return_value=subprocess.CompletedProcess(args=["sops"], returncode=0, stdout=""))
    monkeypatch.setattr("homelabctl.secrets.subprocess.run", run)

    set_cloudflare_token(path, api_token, sops_executable="sops")

    command = run.call_args.args[0]
    assert api_token not in command
    assert '["cloudflare"]["api_token"]' in command
    assert run.call_args.kwargs["input"] == json.dumps(api_token)


def test_cloudflare_validation_ignores_unfinished_proxmox_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_encrypted_file(tmp_path / "secrets.enc.yaml")
    decrypted = yaml.safe_dump(
        {
            "schema_version": 1,
            "proxmox": {"api_token": "replace-with-proxmox-api-token-secret"},
            "cloudflare": {"api_token": CLOUDFLARE_TOKEN},
        }
    )
    monkeypatch.setattr(
        "homelabctl.secrets.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["sops", "decrypt"], returncode=0, stdout=decrypted
        ),
    )

    validate_provider_secret(path, "cloudflare", sops_executable="sops")


def test_age_identity_is_created_once_and_only_public_recipient_is_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity_path = tmp_path / "age" / "keys.txt"
    recipient = "age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "-o" in command:
            output = Path(command[command.index("-o") + 1])
            output.write_text("AGE-SECRET-KEY-TEST-ONLY", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout=f"{recipient}\n", stderr="")

    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(identity_path))
    monkeypatch.setattr("homelabctl.secrets.subprocess.run", fake_run)

    path, public_recipient, created = ensure_age_identity(age_keygen_executable="age-keygen")
    _, repeated_recipient, created_again = ensure_age_identity(age_keygen_executable="age-keygen")

    assert path == identity_path
    assert public_recipient == recipient
    assert repeated_recipient == recipient
    assert created
    assert not created_again
    assert "SECRET" not in public_recipient
