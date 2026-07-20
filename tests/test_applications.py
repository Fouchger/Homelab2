from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
import yaml

from homelabctl.applications import (
    COMMUNITY_SCRIPTS_REVISION,
    UPTIME_KUMA_DIST_SHA256,
    UPTIME_KUMA_SOURCE_SHA256,
    ApplicationError,
    application_plan,
    run_applications,
)
from homelabctl.configuration import save_config
from homelabctl.models import HomelabConfig
from homelabctl.secrets import ProviderSecret, SecretBundle, ServiceSecret


def _config(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "ansible" / "applications").mkdir(parents=True)
    (tmp_path / "ansible" / "applications" / "uptime-kuma.yml").write_text(
        "---\n", encoding="utf-8"
    )
    data = {
        "network": {"management_cidr": "192.168.10.0/24", "gateway": "192.168.10.1"},
        "automation": {
            "ssh_private_key": str(tmp_path / "key"),
            "ssh_public_keys": ["ssh-ed25519 AAAAC3NzaCTest automation"],
        },
        "proxmox": {
            "containers": [
                {
                    "key": "monitoring",
                    "vm_id": 200,
                    "hostname": "monitoring",
                    "template_file_id": "local:vztmpl/debian.tar.zst",
                    "address": "192.168.10.20/24",
                }
            ]
        },
        "applications": {
            "uptime-kuma": {"type": "uptime-kuma", "guest": "monitoring", "port": 3001}
        },
    }
    return save_config(HomelabConfig.model_validate(data), tmp_path / "config" / "site.yaml")


def test_plan_exposes_immutable_revision_and_checksums(tmp_path: Path) -> None:
    lines = application_plan(_config(tmp_path))
    rendered = "\n".join(lines)
    assert COMMUNITY_SCRIPTS_REVISION in rendered
    assert UPTIME_KUMA_SOURCE_SHA256 in rendered
    assert UPTIME_KUMA_DIST_SHA256 in rendered


def test_application_target_must_exist() -> None:
    with pytest.raises(ValueError, match="unknown container"):
        HomelabConfig.model_validate(
            {"applications": {"uptime-kuma": {"type": "uptime-kuma", "guest": "missing"}}}
        )


def test_check_uses_filtered_runtime_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _config(tmp_path)
    inventory_path = tmp_path / ".cache" / "ansible" / "inventory.json"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text(
        json.dumps(
            {
                "all": {
                    "hosts": {
                        "monitoring": {"ansible_host": "192.168.10.20"},
                        "other": {"ansible_host": "192.168.10.21"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "homelabctl.applications.generate_inventory", lambda path: (inventory_path, ())
    )
    monkeypatch.setattr("homelabctl.applications.shutil.which", lambda name: "ansible-playbook")
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, "monitoring : ok=12 changed=0 failed=0\n", "")

    monkeypatch.setattr("homelabctl.applications.subprocess.run", run)
    result = run_applications(config_path, check=True)
    filtered = json.loads(
        (tmp_path / ".cache" / "ansible" / "applications.json").read_text(encoding="utf-8")
    )
    assert set(filtered["all"]["hosts"]) == {"monitoring"}
    assert filtered["all"]["hosts"]["monitoring"]["ansible_user"] == "automation"
    assert filtered["all"]["hosts"]["monitoring"]["ansible_become"] is True
    assert "--check" in commands[0]
    assert result.guest == "monitoring"


def test_empty_catalog_refuses_execution(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    path = save_config(HomelabConfig(), tmp_path / "site.yaml")
    with pytest.raises(ApplicationError, match="exactly one"):
        run_applications(path, check=True)


def test_helper_owned_application_uses_provisioned_root_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = yaml.safe_load(
        (Path(__file__).parents[1] / "config" / "examples" / "dns-core-site.yaml").read_text(
            encoding="utf-8"
        )
    )
    data["automation"]["ssh_public_key_files"] = []
    data["automation"]["ssh_public_keys"] = ["ssh-ed25519 AAAAC3NzaCTest automation"]
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    config_path = save_config(HomelabConfig.model_validate(data), tmp_path / "config" / "site.yaml")
    (tmp_path / ".cache" / "ansible").mkdir(parents=True)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps({"all": {"hosts": {"dns-core01": {"ansible_host": "192.168.30.53"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "homelabctl.applications.generate_inventory", lambda path: (inventory_path, ())
    )
    monkeypatch.setattr("homelabctl.applications.shutil.which", lambda name: "ansible-playbook")
    monkeypatch.setattr(
        "homelabctl.applications.load_secrets",
        lambda **kwargs: SecretBundle(
            proxmox=ProviderSecret(api_token="test-proxmox-token"),
            credentials={"technitium-admin": ServiceSecret(value="unique-dns-password")},
        ),
    )
    monkeypatch.setattr(
        "homelabctl.applications.load_mikrotik_desired_state",
        lambda path: type(
            "Router", (), {"networks": [type("Network", (), {"cidr": "192.168.30.0/24"})()]}
        )(),
    )
    monkeypatch.setattr(
        "homelabctl.applications.subprocess.run",
        lambda command, **kwargs: CompletedProcess(command, 0, "dns-core01 : ok=1 changed=0\n", ""),
    )

    run_applications(config_path, check=True)

    filtered = json.loads(
        (tmp_path / ".cache" / "ansible" / "applications.json").read_text(encoding="utf-8")
    )
    assert filtered["all"]["hosts"]["dns-core01"]["ansible_user"] == "root"
    assert filtered["all"]["hosts"]["dns-core01"]["ansible_become"] is False
