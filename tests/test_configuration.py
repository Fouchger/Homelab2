from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from homelabctl.configuration import ConfigurationError, load_config, save_config, write_schema
from homelabctl.models import default_config
from homelabctl.operations import execute


def test_configuration_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "site.yaml"
    expected = default_config()

    saved = save_config(expected, path)
    actual = load_config(path)

    assert saved == path
    assert actual == expected
    assert not list(tmp_path.glob("*.tmp"))


def test_configuration_without_cloudflare_section_uses_empty_domains(tmp_path: Path) -> None:
    path = tmp_path / "legacy-site.yaml"
    config = default_config().model_dump(mode="json")
    config.pop("cloudflare")
    path.write_text(yaml.safe_dump(config), encoding="utf-8")

    loaded = load_config(path)

    assert loaded.cloudflare.domains == []


def test_missing_configuration_has_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Configuration not found"):
        load_config(tmp_path / "missing.yaml")


def test_schema_can_be_generated(tmp_path: Path) -> None:
    path = write_schema(tmp_path / "site.schema.json")

    content = path.read_text(encoding="utf-8")
    assert '"HomelabConfig"' in content
    assert '"schema_version"' in content


def test_validate_operation_reports_site(tmp_path: Path) -> None:
    path = save_config(default_config(), tmp_path / "site.yaml")

    result = execute("validate", path)

    assert result.succeeded
    assert "Site: homelab" in result.lines
