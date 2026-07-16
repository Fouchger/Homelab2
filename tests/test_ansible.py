from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from homelabctl.ansible import AnsibleError, generate_inventory, run_baseline
from homelabctl.configuration import save_config
from homelabctl.models import HomelabConfig
from homelabctl.progress import reporting

PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey homelab"


def _site(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    key = tmp_path / "automation"
    key.write_text("private-test-placeholder", encoding="utf-8")
    Path(f"{key}.pub").write_text(PUBLIC_KEY, encoding="utf-8")
    config = HomelabConfig.model_validate(
        {
            "network": {"management_cidr": "192.168.10.0/24", "gateway": "192.168.10.1"},
            "automation": {
                "ssh_private_key": str(key),
                "ssh_public_keys": [PUBLIC_KEY],
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
        }
    )
    path = tmp_path / "config" / "sites" / "local.yaml"
    save_config(config, path)
    (tmp_path / "infrastructure").mkdir()
    (tmp_path / "ansible").mkdir()
    (tmp_path / "ansible" / "baseline.yml").write_text("---\n", encoding="utf-8")
    return path


def test_inventory_is_derived_from_tofu_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _site(tmp_path)

    environment: dict[str, str] = {}

    def run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        environment.update(kwargs["env"])
        return CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "monitoring": {
                        "hostname": "monitoring",
                        "management_address": "192.168.10.20",
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("homelabctl.ansible.subprocess.run", run)
    inventory_path, hosts = generate_inventory(path, tofu_executable="tofu")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert hosts == ("monitoring: root@192.168.10.20 (monitoring)",)
    assert inventory["all"]["hosts"]["monitoring"]["ansible_user"] == "root"
    assert "private-test-placeholder" not in inventory_path.read_text(encoding="utf-8")
    assert environment["TF_DATA_DIR"] == str(tmp_path / ".cache" / "tofu" / "data")
    assert environment["TF_INPUT"] == "0"


def test_inventory_refuses_state_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _site(tmp_path)
    monkeypatch.setattr(
        "homelabctl.ansible.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args=[], returncode=0, stdout="{}", stderr=""),
    )
    with pytest.raises(AnsibleError, match="does not match"):
        generate_inventory(path, tofu_executable="tofu")


def test_check_mode_is_passed_to_ansible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _site(tmp_path)
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        if "output" in command:
            output = {
                "monitoring": {
                    "hostname": "monitoring",
                    "management_address": "192.168.10.20",
                }
            }
            return CompletedProcess(command, 0, json.dumps(output), "")
        return CompletedProcess(
            command, 0, "monitoring : ok=7 changed=0 unreachable=0 failed=0\n", ""
        )

    monkeypatch.setattr("homelabctl.ansible.subprocess.run", run)
    result = run_baseline(
        path, check=True, tofu_executable="tofu", ansible_executable="ansible-playbook"
    )
    assert "--check" in commands[-1]
    assert result.changed is False


def test_menu_mode_streams_baseline_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _site(tmp_path)

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        output = {
            "monitoring": {
                "hostname": "monitoring",
                "management_address": "192.168.10.20",
            }
        }
        return CompletedProcess(command, 0, json.dumps(output), "")

    class Process:
        stdout = StringIO("TASK [Gathering Facts]\nmonitoring : ok=7 changed=0\n")
        returncode = 0

        def __enter__(self) -> Process:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def wait(self) -> int:
            return self.returncode

    monkeypatch.setattr("homelabctl.ansible.subprocess.run", run)
    monkeypatch.setattr("homelabctl.ansible.subprocess.Popen", lambda *args, **kwargs: Process())
    lines: list[str] = []
    with reporting(lines.append):
        result = run_baseline(
            path, check=True, tofu_executable="tofu", ansible_executable="ansible-playbook"
        )
    assert lines == ["TASK [Gathering Facts]", "monitoring : ok=7 changed=0"]
    assert result.changed is False
    assert "TASK [Gathering Facts]" in result.diagnostic_log.read_text(encoding="utf-8")


def test_baseline_sets_a_short_ssh_connection_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _site(tmp_path)
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        if "output" in command:
            return CompletedProcess(
                command,
                0,
                json.dumps(
                    {"monitoring": {"hostname": "monitoring", "management_address": "192.168.10.20"}}
                ),
                "",
            )
        return CompletedProcess(command, 0, "monitoring : ok=7 changed=0\n", "")

    monkeypatch.setattr("homelabctl.ansible.subprocess.run", run)
    run_baseline(path, check=True, tofu_executable="tofu", ansible_executable="ansible-playbook")
    assert commands[-1][commands[-1].index("--timeout") :] == ["--timeout", "30", "--check"]
