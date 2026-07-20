"""Versioned whole-homelab desired-state models for Phase 6."""

from __future__ import annotations

import hashlib
import json
import re
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
HOSTNAME_PATTERN = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SECRET_REFERENCE_PATTERN = re.compile(r"^sops://credentials\.[a-z][a-z0-9-]{1,31}\.value$")

GuestRole = Literal[
    "control",
    "network-core",
    "edge",
    "storage",
    "media",
    "application",
    "monitoring-security",
    "test",
    "expansion",
]
GuestLifecycle = Literal["new", "adopted", "protected-existing"]

VMID_RANGES: dict[str, range] = {
    "control": range(200, 220),
    "network-core": range(220, 240),
    "edge": range(240, 300),
    "storage": range(300, 400),
    "media": range(400, 500),
    "application": range(500, 600),
    "monitoring-security": range(600, 700),
    "test": range(700, 800),
    "expansion": range(800, 900),
}


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, validate_default=True)


class ManifestError(RuntimeError):
    """Raised when a whole-site manifest cannot be loaded or written."""


def _normalize_key(value: str) -> str:
    normalized = value.strip().lower()
    if not KEY_PATTERN.fullmatch(normalized):
        raise ValueError("use a stable 2-32 character lowercase key")
    return normalized


class AddressPolicy(ManifestModel):
    static_first: Literal[1] = 1
    static_last: Literal[150] = 150
    dhcp_first: Literal[151] = 151
    dhcp_last: Literal[254] = 254


class NetworkManifest(ManifestModel):
    key: str
    vlan_id: int = Field(ge=1, le=4094)
    cidr: IPv4Network
    gateway: IPv4Address
    purpose: str = Field(min_length=3, max_length=120)
    owner: Literal["mikrotik"] = "mikrotik"
    address_policy: AddressPolicy = Field(default_factory=AddressPolicy)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _normalize_key(value)

    @model_validator(mode="after")
    def validate_network(self) -> NetworkManifest:
        if self.cidr.prefixlen != 24:
            raise ValueError("Phase 6 networks must use /24 subnets")
        if self.gateway not in self.cidr or not (
            self.address_policy.static_first
            <= int(str(self.gateway).split(".")[-1])
            <= self.address_policy.static_last
        ):
            raise ValueError("the gateway must be a static address in host range .1-.150")
        return self


class GuestResources(ManifestModel):
    cores: int = Field(ge=1, le=128)
    memory_mb: int = Field(ge=256, le=1_048_576)
    disk_gb: int = Field(ge=1, le=16_384)


class GuestManifest(ManifestModel):
    key: str
    vm_id: int = Field(ge=100, le=999_999_999)
    hostname: str
    kind: Literal["lxc", "vm", "appliance"]
    role: GuestRole
    lifecycle: GuestLifecycle = "new"
    protected: bool = False
    owner: Literal["opentofu", "manual-protection"] = "opentofu"
    network: str
    address: IPv4Interface
    os_name: str = "ubuntu"
    os_version: str = "24.04"
    os_exception_reason: str | None = None
    resources: GuestResources
    raw_disk_ids: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("key", "network")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return _normalize_key(value)

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not HOSTNAME_PATTERN.fullmatch(normalized):
            raise ValueError("enter a valid lowercase hostname")
        return normalized

    @field_validator("raw_disk_ids")
    @classmethod
    def validate_disk_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("raw disk identifiers must be non-empty and unique")
        return normalized

    @model_validator(mode="after")
    def validate_platform_policy(self) -> GuestManifest:
        if self.lifecycle == "new":
            if self.vm_id not in VMID_RANGES[self.role]:
                valid = VMID_RANGES[self.role]
                raise ValueError(
                    f"new {self.role} guests require VMIDs {valid.start}-{valid.stop - 1}"
                )
            if self.owner != "opentofu":
                raise ValueError("new guests must enter OpenTofu ownership")
        if self.lifecycle == "protected-existing" and not self.protected:
            raise ValueError("protected existing guests must set protected: true")
        if self.protected and self.owner != "manual-protection":
            raise ValueError("protected guests must use manual-protection ownership")
        if self.vm_id == 22000 and self.key != "omv01":
            raise ValueError("VMID 22000 is reserved exclusively for omv01")
        if self.key == "omv01" and self.vm_id != 22000:
            raise ValueError("omv01 must retain VMID 22000")
        if (self.os_name.lower(), self.os_version) != ("ubuntu", "24.04"):
            if not self.os_exception_reason or len(self.os_exception_reason.strip()) < 12:
                raise ValueError("non-Ubuntu 24.04 guests require a documented OS exception")
        elif self.os_exception_reason:
            raise ValueError("Ubuntu 24.04 guests do not need an OS exception")
        if self.raw_disk_ids and not self.protected:
            raise ValueError("raw disk passthrough is allowed only on protected existing guests")
        return self


class CredentialManifest(ManifestModel):
    username: str = Field(min_length=1, max_length=64)
    secret_ref: str

    @field_validator("secret_ref")
    @classmethod
    def validate_secret_reference(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SECRET_REFERENCE_PATTERN.fullmatch(normalized):
            raise ValueError("credential values must use sops://credentials.<key>.value references")
        return normalized

    @property
    def bundle_key(self) -> str:
        return self.secret_ref.removeprefix("sops://credentials.").removesuffix(".value")


class ApplicationManifest(ManifestModel):
    key: str
    guest: str
    runtime: Literal["native", "docker-compose"]
    owner: Literal["homelab2", "docker-compose", "manual-protection"]
    stateful: bool = False
    credential: str | None = None

    @field_validator("key", "guest")
    @classmethod
    def validate_keys(cls, value: str) -> str:
        return _normalize_key(value)


class ExposureManifest(ManifestModel):
    application: str
    mode: Literal["internal", "wireguard", "cloudflare-access", "plex-remote"]
    owner: Literal["mikrotik", "traefik", "dockflare", "plex"]
    approved: bool = False

    @field_validator("application")
    @classmethod
    def validate_application(cls, value: str) -> str:
        return _normalize_key(value)

    @model_validator(mode="after")
    def require_external_approval(self) -> ExposureManifest:
        if self.mode in {"cloudflare-access", "plex-remote"} and not self.approved:
            raise ValueError("external exposure requires explicit approval")
        return self


class BackupManifest(ManifestModel):
    application: str
    destination: str = Field(min_length=2, max_length=128)
    schedule: str = Field(min_length=3, max_length=128)
    restore_test: str = Field(min_length=3, max_length=240)

    @field_validator("application")
    @classmethod
    def validate_application(cls, value: str) -> str:
        return _normalize_key(value)


class CapacityPolicy(ManifestModel):
    host_memory_mb: int = Field(ge=1024)
    existing_peak_memory_mb: int = Field(ge=0)
    reserve_memory_mb: int = Field(default=4096, ge=1024)
    available_storage_gb: int = Field(ge=1)
    reserve_storage_gb: int = Field(default=32, ge=1)


class HomelabManifest(ManifestModel):
    schema_version: Literal[1] = 1
    site: str = "homelab"
    networks: list[NetworkManifest] = Field(min_length=1, max_length=32)
    guests: list[GuestManifest] = Field(min_length=1, max_length=200)
    credentials: dict[str, CredentialManifest] = Field(default_factory=dict, max_length=200)
    applications: list[ApplicationManifest] = Field(default_factory=list, max_length=300)
    exposures: list[ExposureManifest] = Field(default_factory=list, max_length=300)
    backups: list[BackupManifest] = Field(default_factory=list, max_length=300)
    capacity: CapacityPolicy

    @field_validator("site")
    @classmethod
    def validate_site(cls, value: str) -> str:
        return _normalize_key(value)

    @model_validator(mode="after")
    def validate_references_and_collisions(self) -> HomelabManifest:
        self._require_unique(self.networks, "key", "network keys")
        self._require_unique(self.networks, "vlan_id", "VLAN IDs")
        self._require_unique(self.networks, "cidr", "network CIDRs")
        self._require_unique(self.guests, "key", "guest keys")
        self._require_unique(self.guests, "vm_id", "guest VMIDs")
        self._require_unique(self.guests, "hostname", "guest hostnames")
        self._require_unique(self.guests, "address", "guest addresses")
        self._require_unique(self.applications, "key", "application keys")
        self._require_unique(self.backups, "application", "application backup entries")
        exposure_keys = [(exposure.application, exposure.mode) for exposure in self.exposures]
        if len(exposure_keys) != len(set(exposure_keys)):
            raise ValueError("application and exposure mode combinations must be unique")

        network_by_key = {network.key: network for network in self.networks}
        for guest in self.guests:
            network = network_by_key.get(guest.network)
            if network is None:
                raise ValueError(f"guest {guest.key} references unknown network {guest.network}")
            if guest.address.network != network.cidr:
                raise ValueError(f"guest {guest.key} address must use network {network.key}")
            host = int(str(guest.address.ip).split(".")[-1])
            if (
                not (
                    network.address_policy.static_first
                    <= host
                    <= network.address_policy.static_last
                )
                or guest.address.ip == network.gateway
            ):
                raise ValueError(f"guest {guest.key} requires an unused static address in .1-.150")

        guest_keys = {guest.key for guest in self.guests}
        credential_keys = set(self.credentials)
        application_keys = {application.key for application in self.applications}
        for key in credential_keys:
            if key != _normalize_key(key):
                raise ValueError("credential keys must already be normalized lowercase keys")
        for application in self.applications:
            if application.guest not in guest_keys:
                raise ValueError(
                    f"application {application.key} references unknown guest {application.guest}"
                )
            if application.credential and application.credential not in credential_keys:
                raise ValueError(
                    f"application {application.key} references unknown credential "
                    f"{application.credential}"
                )
        for exposure in self.exposures:
            if exposure.application not in application_keys:
                raise ValueError(f"exposure references unknown application {exposure.application}")
            if exposure.application == "plex" and exposure.mode == "cloudflare-access":
                raise ValueError("Plex must never use Cloudflare Tunnel")
        backup_keys = {backup.application for backup in self.backups}
        for backup in self.backups:
            if backup.application not in application_keys:
                raise ValueError(f"backup references unknown application {backup.application}")
        for application in self.applications:
            if application.stateful and application.key not in backup_keys:
                raise ValueError(f"stateful application {application.key} requires a backup policy")

        raw_disks = [disk for guest in self.guests for disk in guest.raw_disk_ids]
        if len(raw_disks) != len(set(raw_disks)):
            raise ValueError("raw disk identifiers must have exactly one guest owner")
        return self

    @staticmethod
    def _require_unique(items: list[object], attribute: str, label: str) -> None:
        values = [getattr(item, attribute) for item in items]
        if len(values) != len(set(values)):
            raise ValueError(f"{label} must be unique")

    @property
    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_manifest(path: str | Path) -> HomelabManifest:
    """Load and validate a Phase 6 manifest without resolving any secret values."""

    manifest_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"Unable to read manifest: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("Manifest root must be a YAML mapping")
    try:
        return HomelabManifest.model_validate(raw)
    except ValueError as exc:
        raise ManifestError(f"Manifest validation failed: {exc}") from exc


def write_manifest_schema(path: str | Path) -> Path:
    """Write the deterministic JSON Schema used by editors and CI."""

    schema_path = Path(path)
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(HomelabManifest.model_json_schema(), indent=2) + "\n"
    try:
        schema_path.write_text(payload, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise ManifestError(f"Unable to write manifest schema: {schema_path}") from exc
    return schema_path
