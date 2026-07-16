from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from homelabctl.configuration import save_config
from homelabctl.models import HomelabConfig, default_config
from homelabctl.operations import check_tofu_foundation
from homelabctl.secrets import ProviderSecret, SecretBundle
from homelabctl.tofu import (
    TofuCheckResult,
    TofuError,
    apply_saved_plan,
    check_foundation,
    tofu_variables,
)


def test_validated_config_maps_to_typed_non_secret_inputs() -> None:
    config = default_config()
    config.proxmox.verify_tls = False

    values = tofu_variables(config)

    assert values["site"] == {
        "name": "homelab",
        "domain": "home.arpa",
        "timezone": "Pacific/Auckland",
        "environment": "production",
    }
    assert values["proxmox"] == {
        "endpoint": "https://pve.home.arpa:8006/",
        "node": "pve",
        "storage": "local-lvm",
        "token_id": "homelab@pve!control-plane",
        "insecure": True,
    }
    assert "api_token" not in values["proxmox"]
    assert values["automation"] == {"ssh_public_keys": []}
    assert values["proxmox_lxcs"] == []
    assert values["cloudflare_records"] == []


def test_public_key_file_is_resolved_for_opentofu(tmp_path: Path) -> None:
    public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest automation"
    public_key_path = tmp_path / "homelab_ed25519.pub"
    public_key_path.write_text(public_key + "\n", encoding="utf-8")
    data = default_config().model_dump(mode="json")
    data["automation"]["ssh_public_key_files"] = [str(public_key_path)]

    values = tofu_variables(HomelabConfig.model_validate(data))

    assert values["automation"] == {"ssh_public_keys": [public_key]}


def test_missing_public_key_file_has_an_actionable_error(tmp_path: Path) -> None:
    data = default_config().model_dump(mode="json")
    data["automation"]["ssh_public_key_files"] = [str(tmp_path / "missing.pub")]

    with pytest.raises(TofuError, match="Unable to read automation SSH public key file"):
        tofu_variables(HomelabConfig.model_validate(data))


def test_managed_resources_map_deterministically() -> None:
    data = default_config().model_dump(mode="json")
    data["automation"]["ssh_public_keys"] = ["ssh-ed25519 AAAAC3NzaCTest automation"]
    data["proxmox"]["containers"] = [
        {
            "key": "web",
            "vm_id": 111,
            "hostname": "web",
            "template_file_id": "local:vztmpl/debian-13-standard.tar.zst",
            "address": "192.168.10.11/24",
        },
        {
            "key": "dns",
            "vm_id": 110,
            "hostname": "dns",
            "template_file_id": "local:vztmpl/debian-13-standard.tar.zst",
            "address": "192.168.10.10/24",
        },
    ]
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "www",
                "type": "CNAME",
                "content": "app.example.com",
            },
            {
                "zone": "example.com",
                "name": "app",
                "type": "A",
                "content": "1.1.1.1",
            },
        ],
    }

    values = tofu_variables(HomelabConfig.model_validate(data))

    assert [container["key"] for container in values["proxmox_lxcs"]] == ["dns", "web"]
    assert [record["name"] for record in values["cloudflare_records"]] == ["app", "www"]


def test_menu_operation_reports_plan_and_log_paths(tmp_path: Path, monkeypatch) -> None:
    expected = TofuCheckResult(
        tmp_path / "site.auto.tfvars.json",
        tmp_path / "foundation.tfplan",
        tmp_path / "opentofu.log",
    )
    check = Mock(return_value=expected)
    monkeypatch.setattr("homelabctl.operations.check_foundation", check)

    result = check_tofu_foundation(tmp_path / "site.yaml")

    assert result.succeeded
    assert f"Non-destructive plan saved at {expected.plan_path}" in result.lines
    assert f"Diagnostic log: {expected.diagnostic_log}" in result.lines


def test_foundation_check_never_writes_runtime_token(tmp_path: Path, monkeypatch) -> None:
    config_path = save_config(default_config(), tmp_path / "site.yaml")
    token = "homelab@pve!control-plane=runtime-secret"
    bundle = SecretBundle(proxmox=ProviderSecret(api_token=token))
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["tofu"], returncode=0, stdout=f"provider output {token}", stderr=""
        )
    )
    monkeypatch.setattr("homelabctl.tofu.load_secrets", Mock(return_value=bundle))
    monkeypatch.setattr("homelabctl.tofu.subprocess.run", run)

    result = check_foundation(config_path, tofu_executable="tofu")

    variables = result.variables_path.read_text(encoding="utf-8")
    diagnostics = result.diagnostic_log.read_text(encoding="utf-8")
    assert token not in variables
    assert token not in diagnostics
    assert "[REDACTED]" in diagnostics
    assert len(run.call_args_list) == 4


def test_foundation_check_redacts_cloudflare_token(tmp_path: Path, monkeypatch) -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "app",
                "type": "A",
                "content": "1.1.1.1",
            }
        ],
    }
    config_path = save_config(HomelabConfig.model_validate(data), tmp_path / "site.yaml")
    proxmox_token = "proxmox-runtime-secret"
    cloudflare_token = "cloudflare-runtime-secret"
    bundle = SecretBundle(
        proxmox=ProviderSecret(api_token=proxmox_token),
        cloudflare=ProviderSecret(api_token=cloudflare_token),
    )
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["tofu"],
            returncode=0,
            stdout=f"provider output {proxmox_token} and {cloudflare_token}",
            stderr="",
        )
    )
    load = Mock(return_value=bundle)
    monkeypatch.setattr("homelabctl.tofu.load_secrets", load)
    monkeypatch.setattr("homelabctl.tofu.subprocess.run", run)

    result = check_foundation(config_path, tofu_executable="tofu")

    diagnostics = result.diagnostic_log.read_text(encoding="utf-8")
    assert proxmox_token not in diagnostics
    assert cloudflare_token not in diagnostics
    assert diagnostics.count("[REDACTED]") >= 2
    assert run.call_args.kwargs["env"]["CLOUDFLARE_API_TOKEN"] == cloudflare_token
    assert load.call_args.kwargs["config"].cloudflare.records


def test_saved_plan_apply_supplies_runtime_credentials_and_exact_plan(
    tmp_path: Path, monkeypatch
) -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "acceptance",
                "type": "CNAME",
                "content": "target.example.net",
            }
        ],
    }
    config_path = save_config(HomelabConfig.model_validate(data), tmp_path / "site.yaml")
    plan_path = tmp_path / "artifacts" / "foundation.tfplan"
    plan_path.parent.mkdir()
    plan_path.write_bytes(b"saved-plan")
    (tmp_path / "infrastructure").mkdir()
    proxmox_token = "proxmox-runtime-secret"
    cloudflare_token = "cloudflare-runtime-secret"
    bundle = SecretBundle(
        proxmox=ProviderSecret(api_token=proxmox_token),
        cloudflare=ProviderSecret(api_token=cloudflare_token),
    )
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["tofu"],
            returncode=0,
            stdout=f"applied with {proxmox_token} and {cloudflare_token}",
            stderr="",
        )
    )
    monkeypatch.setattr("homelabctl.tofu.load_secrets", Mock(return_value=bundle))
    monkeypatch.setattr("homelabctl.tofu.subprocess.run", run)

    result = apply_saved_plan(config_path, tofu_executable="tofu")

    assert result.plan_path == plan_path
    assert run.call_args.args[0] == [
        "tofu",
        "apply",
        "-lock=true",
        "-lock-timeout=30s",
        "-input=false",
        str(plan_path),
    ]
    assert run.call_args.kwargs["env"]["CLOUDFLARE_API_TOKEN"] == cloudflare_token
    assert run.call_args.kwargs["env"]["TF_VAR_proxmox_api_token"] == proxmox_token
    diagnostics = result.diagnostic_log.read_text(encoding="utf-8")
    assert proxmox_token not in diagnostics
    assert cloudflare_token not in diagnostics
    assert diagnostics.count("[REDACTED]") >= 2


def test_saved_plan_apply_requires_existing_plan(tmp_path: Path, monkeypatch) -> None:
    config_path = save_config(default_config(), tmp_path / "site.yaml")
    monkeypatch.setattr("homelabctl.tofu.load_secrets", Mock())

    with pytest.raises(TofuError, match="Run `task tofu:check` first"):
        apply_saved_plan(config_path, tofu_executable="tofu")
