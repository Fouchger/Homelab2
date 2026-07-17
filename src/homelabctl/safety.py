"""Provider-independent admission and no-destroy rules for Phase 6 plans."""

from __future__ import annotations

import re
from ipaddress import IPv4Address
from typing import Literal

from pydantic import Field, field_validator, model_validator

from homelabctl.manifest import HomelabManifest, ManifestModel

DestructiveAction = Literal["stop", "destroy", "replace", "detach", "reclaim"]
PlanAction = Literal[
    "create", "read", "update", "noop", "stop", "destroy", "replace", "detach", "reclaim"
]


class SafetyRefusal(RuntimeError):
    """Raised before provider execution when a plan violates the safety boundary."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("Unsafe plan refused:\n- " + "\n- ".join(reasons))


class DiscoverySnapshot(ManifestModel):
    vm_ids: set[int] = Field(default_factory=set)
    addresses: set[IPv4Address] = Field(default_factory=set)
    raw_disk_ids: set[str] = Field(default_factory=set)


class PlannedChange(ManifestModel):
    resource_type: Literal["guest", "raw-disk", "network", "application", "backup"]
    resource_id: str
    action: PlanAction
    vm_id: int | None = None
    address: IPv4Address | None = None
    raw_disk_id: str | None = None

    @model_validator(mode="after")
    def require_immutable_identifier(self) -> PlannedChange:
        if self.resource_type == "guest" and self.vm_id is None:
            raise ValueError("guest plan changes require a VMID")
        if self.resource_type == "raw-disk" and not self.raw_disk_id:
            raise ValueError("raw-disk plan changes require a raw disk identifier")
        return self


class PlanContract(ManifestModel):
    run_id: str = Field(min_length=8, max_length=80)
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    discovery_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    changes: list[PlannedChange] = Field(default_factory=list)
    approved: bool = False


class ApplyContract(ManifestModel):
    run_id: str = Field(min_length=8, max_length=80)
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_by: str = Field(min_length=2, max_length=80)
    production_mutation_enabled: bool = False

    @model_validator(mode="after")
    def require_explicit_mutation_enablement(self) -> ApplyContract:
        if not self.production_mutation_enabled:
            raise ValueError("apply requires an explicitly enabled production mutation checkpoint")
        return self


class ResumeContract(ManifestModel):
    run_id: str = Field(min_length=8, max_length=80)
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    completed_stages: list[str] = Field(default_factory=list)


class EvidenceContract(ManifestModel):
    run_id: str = Field(min_length=8, max_length=80)
    status: Literal["planned", "refused", "completed", "failed"]
    messages: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("messages")
    @classmethod
    def refuse_secret_material(cls, value: list[str]) -> list[str]:
        secret_assignment = re.compile(
            r"(?:password|api[_-]?token|private[_-]?key|secret)\s*[:=]",
            re.IGNORECASE,
        )
        if any(secret_assignment.search(message) for message in value):
            raise ValueError("evidence must not contain secret material")
        return value


def admit_plan(
    manifest: HomelabManifest,
    discovery: DiscoverySnapshot,
    changes: list[PlannedChange],
) -> None:
    """Refuse collisions, capacity pressure, and destructive discovered-resource actions."""

    reasons: list[str] = []
    protected_vm_ids = discovery.vm_ids | {
        guest.vm_id for guest in manifest.guests if guest.protected
    }
    protected_disks = discovery.raw_disk_ids | {
        disk for guest in manifest.guests if guest.protected for disk in guest.raw_disk_ids
    }

    for change in changes:
        if change.action in {"stop", "destroy", "replace"} and change.vm_id in protected_vm_ids:
            reasons.append(
                f"{change.action} is forbidden for discovered/protected VMID {change.vm_id}"
            )
        if (
            change.action in {"detach", "reclaim", "destroy", "replace"}
            and change.raw_disk_id in protected_disks
        ):
            reasons.append(
                f"{change.action} is forbidden for discovered/protected disk {change.raw_disk_id}"
            )

    for guest in manifest.guests:
        if guest.lifecycle != "new":
            continue
        if guest.vm_id in discovery.vm_ids:
            reasons.append(f"new guest {guest.key} collides with discovered VMID {guest.vm_id}")
        if guest.address.ip in discovery.addresses:
            reasons.append(
                f"new guest {guest.key} collides with discovered address {guest.address.ip}"
            )

    new_guests = [guest for guest in manifest.guests if guest.lifecycle == "new"]
    requested_memory = sum(guest.resources.memory_mb for guest in new_guests)
    memory_total = (
        manifest.capacity.existing_peak_memory_mb
        + manifest.capacity.reserve_memory_mb
        + requested_memory
    )
    if memory_total > manifest.capacity.host_memory_mb:
        reasons.append(
            "memory admission failed: existing peak, new guests, and reserve exceed host capacity"
        )
    requested_storage = sum(guest.resources.disk_gb for guest in new_guests)
    if (
        requested_storage + manifest.capacity.reserve_storage_gb
        > manifest.capacity.available_storage_gb
    ):
        reasons.append("storage admission failed: new disks and reserve exceed available storage")

    if reasons:
        raise SafetyRefusal(reasons)
