"""Read-only discovery parsing and sanitized Phase 6 admission evidence."""

from __future__ import annotations

import hashlib
import json
import re
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal

from pydantic import Field

from homelabctl.manifest import HomelabManifest, ManifestModel, load_manifest
from homelabctl.safety import DiscoverySnapshot, SafetyRefusal, admit_plan

SECRET_ASSIGNMENT = re.compile(
    r"\b(?:password|passphrase|pre-shared-key|private-key|secret|token|community)"
    r"\s*[:=]\s*(?P<value>\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)
GUEST_JSON_MARKER = "### Guests"
STATIC_ADDRESS = re.compile(r"\bip=(\d{1,3}(?:\.\d{1,3}){3})/\d{1,2}\b")
RAW_DISK = re.compile(r"/dev/disk/by-id/([^,\s]+)")
ROUTER_GATEWAY = re.compile(
    r"\baddress=192\.168\.\d{1,3}\.1/24\b.*\binterface=VLAN\d+", re.IGNORECASE
)
ROUTER_DHCP = re.compile(r'\bname="dhcp-vlan\d+"', re.IGNORECASE)
ROUTER_WIFI = re.compile(r'\bname="(wifi[^\"]*)"', re.IGNORECASE)


class DiscoveryError(RuntimeError):
    """Raised when ignored discovery input is unsafe or cannot be parsed."""


class DiscoveredGuest(ManifestModel):
    vm_id: int = Field(ge=100)
    kind: Literal["lxc", "qemu"]
    status: str
    memory_mb: int = Field(ge=0)
    disk_gb: int = Field(ge=0)


class ProxmoxDiscovery(ManifestModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    guests: list[DiscoveredGuest]
    addresses: set[IPv4Address]
    raw_disk_ids: set[str]

    def safety_snapshot(self) -> DiscoverySnapshot:
        return DiscoverySnapshot(
            vm_ids={guest.vm_id for guest in self.guests},
            addresses=self.addresses,
            raw_disk_ids=self.raw_disk_ids,
        )


class RouterDiscovery(ManifestModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    gateway_count: int = Field(ge=0)
    dhcp_server_count: int = Field(ge=0)
    wifi_interface_count: int = Field(ge=0)


class ReadOnlyAdmissionEvidence(ManifestModel):
    schema_version: Literal[1] = 1
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    proxmox_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    router_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    discovered_guest_count: int = Field(ge=0)
    protected_guest_count: int = Field(ge=0)
    discovered_static_address_count: int = Field(ge=0)
    protected_raw_disk_count: int = Field(ge=0)
    router_gateway_count: int = Field(ge=0)
    router_dhcp_server_count: int = Field(ge=0)
    router_wifi_interface_count: int = Field(ge=0)
    admission: Literal["pass", "refused"]
    refusal_categories: list[
        Literal[
            "vmid-collision", "address-collision", "memory-capacity", "storage-capacity", "other"
        ]
    ] = Field(default_factory=list)
    production_mutation_performed: Literal[False] = False


def _read_safe_snapshot(path: str | Path) -> tuple[Path, str, str]:
    source = Path(path).expanduser().resolve()
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise DiscoveryError(f"Unable to read discovery snapshot: {source}") from exc
    if any(
        match.group("value").strip('"').lower() != "<redacted>"
        for match in SECRET_ASSIGNMENT.finditer(text)
    ):
        raise DiscoveryError(
            f"Refusing discovery snapshot with an unredacted secret-shaped assignment: {source}"
        )
    return source, text, hashlib.sha256(raw).hexdigest()


def parse_proxmox_snapshot(path: str | Path) -> ProxmoxDiscovery:
    """Parse only the minimum immutable identities needed by the safety engine."""

    source, text, digest = _read_safe_snapshot(path)
    marker_index = text.find(GUEST_JSON_MARKER)
    if marker_index < 0:
        raise DiscoveryError(f"Proxmox guest section was not found: {source}")
    guest_payload: list[object] | None = None
    for line in text[marker_index + len(GUEST_JSON_MARKER) :].splitlines():
        candidate = line.strip()
        if not candidate.startswith("["):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"Proxmox guest JSON is invalid: {source}") from exc
        if isinstance(parsed, list):
            guest_payload = parsed
            break
    if guest_payload is None:
        raise DiscoveryError(f"Proxmox guest JSON was not found: {source}")

    guests: list[DiscoveredGuest] = []
    for item in guest_payload:
        if not isinstance(item, dict):
            raise DiscoveryError(f"Proxmox guest JSON contains an invalid entry: {source}")
        try:
            guests.append(
                DiscoveredGuest(
                    vm_id=item["vmid"],
                    kind=item["type"],
                    status=str(item.get("status", "unknown")),
                    memory_mb=int(item.get("maxmem", 0)) // (1024 * 1024),
                    disk_gb=int(item.get("maxdisk", 0)) // (1024 * 1024 * 1024),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DiscoveryError(
                f"Proxmox guest JSON is missing required identity data: {source}"
            ) from exc

    addresses: set[IPv4Address] = set()
    for match in STATIC_ADDRESS.finditer(text):
        try:
            addresses.add(IPv4Address(match.group(1)))
        except ValueError as exc:
            raise DiscoveryError(
                f"Proxmox snapshot contains an invalid static address: {source}"
            ) from exc
    return ProxmoxDiscovery(
        source_sha256=digest,
        guests=guests,
        addresses=addresses,
        raw_disk_ids=set(RAW_DISK.findall(text)),
    )


def parse_router_snapshot(path: str | Path) -> RouterDiscovery:
    """Count topology features without retaining addresses, SSIDs, MACs, or public WAN details."""

    _, text, digest = _read_safe_snapshot(path)
    return RouterDiscovery(
        source_sha256=digest,
        gateway_count=len(ROUTER_GATEWAY.findall(text)),
        dhcp_server_count=len(ROUTER_DHCP.findall(text)),
        wifi_interface_count=len(set(ROUTER_WIFI.findall(text))),
    )


def build_read_only_evidence(
    manifest: HomelabManifest,
    proxmox: ProxmoxDiscovery,
    router: RouterDiscovery,
) -> ReadOnlyAdmissionEvidence:
    """Run collision/capacity admission with an empty, non-mutating change set."""

    admission: Literal["pass", "refused"] = "pass"
    categories: list[str] = []
    try:
        admit_plan(manifest, proxmox.safety_snapshot(), [])
    except SafetyRefusal as exc:
        admission = "refused"
        for reason in exc.reasons:
            if "VMID" in reason:
                categories.append("vmid-collision")
            elif "address" in reason:
                categories.append("address-collision")
            elif reason.startswith("memory admission"):
                categories.append("memory-capacity")
            elif reason.startswith("storage admission"):
                categories.append("storage-capacity")
            else:
                categories.append("other")
    return ReadOnlyAdmissionEvidence(
        manifest_sha256=manifest.digest,
        proxmox_source_sha256=proxmox.source_sha256,
        router_source_sha256=router.source_sha256,
        discovered_guest_count=len(proxmox.guests),
        protected_guest_count=len(proxmox.guests),
        discovered_static_address_count=len(proxmox.addresses),
        protected_raw_disk_count=len(proxmox.raw_disk_ids),
        router_gateway_count=router.gateway_count,
        router_dhcp_server_count=router.dhcp_server_count,
        router_wifi_interface_count=router.wifi_interface_count,
        admission=admission,
        refusal_categories=sorted(set(categories)),
    )


def write_read_only_evidence(
    manifest_path: str | Path,
    proxmox_path: str | Path,
    router_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Write a secret-free summary; exact discovered identifiers stay only in memory."""

    evidence = build_read_only_evidence(
        load_manifest(manifest_path),
        parse_proxmox_snapshot(proxmox_path),
        parse_router_snapshot(router_path),
    )
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.write_text(
            json.dumps(evidence.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise DiscoveryError(f"Unable to write read-only evidence: {destination}") from exc
    return destination
