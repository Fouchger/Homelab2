from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from homelabctl.ansible_setup import install_ansible_prerequisites, setup_plan


def _project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    requirements = tmp_path / "ansible" / "requirements.yml"
    requirements.parent.mkdir()
    requirements.write_text("---\ncollections: []\n", encoding="utf-8")
    config = tmp_path / "config" / "sites" / "local.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("schema_version: 1\n", encoding="utf-8")
    return config


def test_setup_plan_displays_system_and_locked_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _project(tmp_path)
    monkeypatch.setattr("homelabctl.ansible_setup.shutil.which", lambda name: None)
    rendered = "\n".join(setup_plan(config))
    assert "ansible-core" in rendered
    assert "requirements.yml" in rendered
    assert "installation is required" in rendered


def test_existing_ansible_installs_locked_collections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _project(tmp_path)
    locations = {
        "ansible-playbook": "/usr/bin/ansible-playbook",
        "ansible-galaxy": "/usr/bin/ansible-galaxy",
    }
    monkeypatch.setattr("homelabctl.ansible_setup.shutil.which", locations.get)
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, "installed\n", "")

    monkeypatch.setattr("homelabctl.ansible_setup.subprocess.run", run)
    result = install_ansible_prerequisites(config)
    assert commands == [
        [
            "/usr/bin/ansible-galaxy",
            "collection",
            "install",
            "--requirements-file",
            str(tmp_path / "ansible" / "requirements.yml"),
        ]
    ]
    assert result.ansible_playbook == "/usr/bin/ansible-playbook"
    assert "exit_code=0" in result.diagnostic_log.read_text(encoding="utf-8")
