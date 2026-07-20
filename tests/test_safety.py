from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from homelabctl.manifest import HomelabManifest
from homelabctl.safety import (
    ApplyContract,
    DiscoverySnapshot,
    EvidenceContract,
    PlannedChange,
    SafetyRefusal,
    admit_plan,
)


def manifest() -> HomelabManifest:
    path = Path(__file__).parents[1] / "config" / "examples" / "future-state.yaml"
    return HomelabManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("action", ["stop", "destroy", "replace"])
def test_discovered_guest_can_never_enter_destructive_plan(action: str) -> None:
    snapshot = DiscoverySnapshot(vm_ids={105})
    change = PlannedChange(
        resource_type="guest", resource_id="legacy-plex", action=action, vm_id=105
    )

    with pytest.raises(SafetyRefusal, match=f"{action} is forbidden"):
        admit_plan(manifest(), snapshot, [change])


@pytest.mark.parametrize("action", ["detach", "reclaim", "destroy", "replace"])
def test_discovered_raw_disk_can_never_enter_destructive_plan(action: str) -> None:
    snapshot = DiscoverySnapshot(raw_disk_ids={"disk-by-id-1"})
    change = PlannedChange(
        resource_type="raw-disk",
        resource_id="omv-disk",
        action=action,
        raw_disk_id="disk-by-id-1",
    )

    with pytest.raises(SafetyRefusal, match="forbidden for discovered/protected disk"):
        admit_plan(manifest(), snapshot, [change])


def test_new_vmid_and_address_collisions_are_refused() -> None:
    snapshot = DiscoverySnapshot(vm_ids={200}, addresses={"192.168.30.53"})

    with pytest.raises(SafetyRefusal) as error:
        admit_plan(manifest(), snapshot, [])

    assert "collides with discovered VMID 200" in str(error.value)
    assert "collides with discovered address 192.168.30.53" in str(error.value)


def test_unsafe_memory_and_storage_pressure_are_refused() -> None:
    data = manifest().model_dump(mode="json")
    data["capacity"]["host_memory_mb"] = 8192
    data["capacity"]["available_storage_gb"] = 100

    with pytest.raises(SafetyRefusal) as error:
        admit_plan(HomelabManifest.model_validate(data), DiscoverySnapshot(), [])

    assert "memory admission failed" in str(error.value)
    assert "storage admission failed" in str(error.value)


def test_apply_is_disabled_until_explicit_checkpoint() -> None:
    with pytest.raises(ValidationError, match="explicitly enabled"):
        ApplyContract(
            run_id="phase6-run-001",
            manifest_digest="a" * 64,
            plan_digest="b" * 64,
            approved_by="operator",
        )


def test_evidence_contract_refuses_secret_material() -> None:
    with pytest.raises(ValidationError, match="must not contain secret"):
        EvidenceContract(
            run_id="phase6-run-001",
            status="failed",
            messages=["api_token=should-never-appear"],
        )


@pytest.mark.parametrize(
    ("resource_type", "message"),
    [("guest", "require a VMID"), ("raw-disk", "require a raw disk identifier")],
)
def test_plan_changes_cannot_omit_protected_identifiers(resource_type: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        PlannedChange(resource_type=resource_type, resource_id="unsafe", action="destroy")
