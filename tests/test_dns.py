from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest
import yaml

from homelabctl.configuration import save_config
from homelabctl.dns import (
    BUILD_FUNC_SHA256,
    COMMUNITY_SCRIPTS_REVISION,
    REMOTE_DNS_PROVISION_SCRIPT,
    TECHNITIUM_ENTRY_SHA256,
    DnsProvisionError,
    dns_provision_plan,
    provision_dns_lxc,
)
from homelabctl.models import HomelabConfig, default_config
from homelabctl.operations import prepare_network_foundation

EXAMPLE = Path(__file__).parents[1] / "config" / "examples" / "dns-core-site.yaml"
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey homelab"


def _site(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["automation"]["ssh_public_key_files"] = []
    data["automation"]["ssh_public_keys"] = [PUBLIC_KEY]
    return save_config(
        HomelabConfig.model_validate(data), tmp_path / "config" / "sites" / "local.yaml"
    )


def test_dns_plan_uses_one_helper_owner_and_immutable_revision(tmp_path: Path) -> None:
    plan = dns_provision_plan(_site(tmp_path))
    rendered = "\n".join(plan.lines)

    assert plan.guest.vm_id == 220
    assert plan.guest.provisioner == "community-script"
    assert COMMUNITY_SCRIPTS_REVISION in rendered
    assert TECHNITIUM_ENTRY_SHA256 in rendered
    assert BUILD_FUNC_SHA256 in rendered
    assert "never overwritten" in rendered


def test_menu_prepares_dns_in_active_site_without_replacing_existing_resources(
    tmp_path: Path,
) -> None:
    data = default_config().model_dump(mode="json")
    data["network"].update(
        management_cidr="192.168.30.0/24",
        gateway="192.168.30.1",
        dns_servers=["192.168.30.2", "192.168.30.3"],
        vlan_id=30,
    )
    data["automation"]["ssh_public_keys"] = [PUBLIC_KEY]
    data["proxmox"]["containers"] = [
        {
            "key": "monitoring",
            "vm_id": 201,
            "hostname": "monitoring",
            "template_file_id": "local:vztmpl/ubuntu-24.04-standard.tar.zst",
            "address": "192.168.30.201/24",
        }
    ]
    data["applications"] = {
        "uptime-kuma": {"type": "uptime-kuma", "guest": "monitoring", "port": 3001}
    }
    config = HomelabConfig.model_validate(data)
    path = save_config(config, tmp_path / "site.yaml")

    first = prepare_network_foundation(path)
    second = prepare_network_foundation(path)
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert first.succeeded and second.succeeded
    assert {guest["key"] for guest in saved["proxmox"]["containers"]} == {
        "monitoring",
        "dns-core01",
    }
    assert set(saved["applications"]) == {"uptime-kuma", "technitium"}
    assert saved["applications"]["technitium"]["credential"] == "technitium-admin"


def test_dns_plan_refuses_opentofu_ownership(tmp_path: Path) -> None:
    path = _site(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    dns = next(item for item in data["proxmox"]["containers"] if item["key"] == "dns-core01")
    dns["provisioner"] = "opentofu"
    dns.pop("helper_script")
    save_config(HomelabConfig.model_validate(data), path)

    with pytest.raises(DnsProvisionError, match="provisioner=community-script"):
        dns_provision_plan(path)


def test_dns_apply_passes_pins_to_remote_script_and_accepts_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _site(tmp_path)
    run = Mock(
        return_value=CompletedProcess(
            args=["ssh"], returncode=0, stdout="HOMELAB_DNS_RESULT=created\n", stderr=""
        )
    )
    monkeypatch.setattr("homelabctl.dns.subprocess.run", run)

    result = provision_dns_lxc(path, ssh_executable="ssh")

    assert result.created
    assert result.address == "192.168.30.53"
    command = run.call_args.args[0]
    assert COMMUNITY_SCRIPTS_REVISION in command
    assert TECHNITIUM_ENTRY_SHA256 in command
    assert BUILD_FUNC_SHA256 in command
    assert run.call_args.kwargs["input"] == REMOTE_DNS_PROVISION_SCRIPT
    assert "ProxmoxVE/main/" in REMOTE_DNS_PROVISION_SCRIPT
    assert 'sed -i "s#https://raw.githubusercontent.com' in REMOTE_DNS_PROVISION_SCRIPT
