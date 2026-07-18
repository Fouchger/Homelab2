from __future__ import annotations

import json
from pathlib import Path

import pytest

from homelabctl.cli import main
from homelabctl.configuration import save_config
from homelabctl.doctor import CheckResult
from homelabctl.models import default_config


def test_init_validate_and_show_json_succeed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config" / "site.yaml"

    assert main(["init", "--config", str(config_path)]) == 0
    assert config_path.is_file()
    capsys.readouterr()

    assert main(["validate", "--config", str(config_path)]) == 0
    assert "Valid configuration" in capsys.readouterr().out

    assert main(["show", "--config", str(config_path), "--json"]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["site"]["name"] == "homelab"
    assert "password" not in json.dumps(rendered).lower()
    assert "token_secret" not in json.dumps(rendered).lower()


def test_init_refuses_to_replace_an_existing_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = save_config(default_config(), tmp_path / "site.yaml")

    assert main(["init", "--config", str(config_path)]) == 2
    assert "Configuration already exists" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["validate", "show"])
def test_config_commands_report_missing_configuration(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yaml"
    arguments = [command, "--config", str(missing)]
    if command == "show":
        arguments.append("--json")

    assert main(arguments) == 2
    assert "Configuration not found" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["validate", "show"])
def test_config_commands_report_invalid_configuration(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("site: []\n", encoding="utf-8")
    arguments = [command, "--config", str(invalid)]
    if command == "show":
        arguments.append("--json")

    assert main(arguments) == 2
    assert "Configuration validation failed" in capsys.readouterr().out


def test_doctor_returns_zero_when_required_checks_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = save_config(default_config(), tmp_path / "site.yaml")
    monkeypatch.setattr(
        "homelabctl.cli.run_checks",
        lambda *_: [CheckResult("Site configuration", "pass", str(config_path))],
    )

    assert main(["doctor", "--config", str(config_path)]) == 0


def test_doctor_returns_one_when_a_required_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = save_config(default_config(), tmp_path / "site.yaml")
    monkeypatch.setattr(
        "homelabctl.cli.run_checks",
        lambda *_: [CheckResult("Task runner", "fail", "task is not installed")],
    )

    assert main(["doctor", "--config", str(config_path)]) == 1


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (None, "Configuration not found"),
        ("[]\n", "Configuration root"),
    ],
)
def test_doctor_reports_configuration_failures(
    contents: str | None,
    expected: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "site.yaml"
    if contents is not None:
        config_path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr("homelabctl.doctor.shutil.which", lambda _: "/usr/bin/tool")

    assert main(["doctor", "--config", str(config_path)]) == 1
    assert expected in capsys.readouterr().out
