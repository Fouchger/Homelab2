from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

from homelabctl.configuration import save_config
from homelabctl.models import HomelabConfig, default_config
from homelabctl.operations import check_tofu_foundation
from homelabctl.secrets import ProviderSecret, SecretBundle
from homelabctl.tofu import TofuCheckResult, check_foundation, tofu_variables


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
