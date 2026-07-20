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
from homelabctl.models import HomelabConfig

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
