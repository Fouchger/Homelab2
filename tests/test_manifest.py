from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from homelabctl.cli import main
from homelabctl.manifest import HomelabManifest, load_manifest, write_manifest_schema


def future_state_data() -> dict[str, object]:
    path = Path(__file__).parents[1] / "config" / "examples" / "future-state.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_complete_future_state_example_validates() -> None:
    manifest = HomelabManifest.model_validate(future_state_data())

    assert manifest.digest == manifest.digest
    assert len(manifest.digest) == 64
    assert {guest.vm_id for guest in manifest.guests} == {201, 220, 240, 400, 22000}
    assert next(guest for guest in manifest.guests if guest.key == "omv01").protected


def test_manifest_loader_and_schema_writer(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "config" / "examples" / "future-state.yaml"
    loaded = load_manifest(source)
    schema_path = write_manifest_schema(tmp_path / "future-state.schema.json")

    assert loaded.site == "homelab"
    assert '"HomelabManifest"' in schema_path.read_text(encoding="utf-8")


def test_manifest_cli_validates_without_resolving_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = Path(__file__).parents[1] / "config" / "examples" / "future-state.yaml"

    assert main(["manifest", "validate", "--file", str(source)]) == 0
    assert "Valid whole-site manifest" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("guest_key", "vm_id", "message"),
    [
        ("control01", 199, "VMIDs 200-219"),
        ("dns01", 240, "VMIDs 220-239"),
        ("edge01", 220, "VMIDs 240-299"),
        ("media01", 399, "VMIDs 400-499"),
    ],
)
def test_new_guest_vmid_groups_are_enforced(guest_key: str, vm_id: int, message: str) -> None:
    data = future_state_data()
    guest = next(item for item in data["guests"] if item["key"] == guest_key)
    guest["vm_id"] = vm_id

    with pytest.raises(ValidationError, match=message):
        HomelabManifest.model_validate(data)


def test_static_and_dhcp_address_contract_is_enforced() -> None:
    data = future_state_data()
    data["guests"][0]["address"] = "192.168.20.201/24"

    with pytest.raises(ValidationError, match=r"static address in \.1-\.99"):
        HomelabManifest.model_validate(data)


def test_nonstandard_os_requires_a_reason() -> None:
    data = future_state_data()
    data["guests"][0]["os_name"] = "debian"
    data["guests"][0]["os_version"] = "13"

    with pytest.raises(ValidationError, match="documented OS exception"):
        HomelabManifest.model_validate(data)

    data["guests"][0]["os_exception_reason"] = "Upstream supports Debian only"
    manifest = HomelabManifest.model_validate(data)
    assert manifest.guests[0].os_name == "debian"


def test_plaintext_credentials_are_not_part_of_the_schema() -> None:
    data = future_state_data()
    data["credentials"]["plex-admin"]["password"] = "do-not-commit-this"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HomelabManifest.model_validate(data)


def test_stateful_application_requires_restore_policy() -> None:
    data = future_state_data()
    data["backups"] = [backup for backup in data["backups"] if backup["application"] != "plex"]

    with pytest.raises(ValidationError, match="stateful application plex"):
        HomelabManifest.model_validate(data)


def test_duplicate_exposure_ownership_is_rejected() -> None:
    data = future_state_data()
    data["exposures"].append(dict(data["exposures"][0]))

    with pytest.raises(ValidationError, match="exposure mode combinations must be unique"):
        HomelabManifest.model_validate(data)


def test_raw_disk_has_exactly_one_protected_owner() -> None:
    data = future_state_data()
    data["guests"][0]["raw_disk_ids"] = ["omv-data-disk-1"]

    with pytest.raises(ValidationError, match="allowed only on protected"):
        HomelabManifest.model_validate(data)
