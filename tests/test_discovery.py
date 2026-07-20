from __future__ import annotations

import json
from pathlib import Path

import pytest

from homelabctl.discovery import (
    DiscoveryError,
    build_read_only_evidence,
    parse_proxmox_snapshot,
    parse_router_snapshot,
    write_read_only_evidence,
)
from homelabctl.manifest import load_manifest


def proxmox_snapshot(*, vm_id: int = 100) -> str:
    guests = json.dumps(
        [
            {
                "vmid": vm_id,
                "type": "lxc",
                "status": "running",
                "maxmem": 1073741824,
                "maxdisk": 8589934592,
            },
            {
                "vmid": 22000,
                "type": "qemu",
                "status": "running",
                "maxmem": 4294967296,
                "maxdisk": 34359738368,
            },
        ]
    )
    return f"""### Guests
{guests}
VMID Status Name
### Guest configuration - sensitive fields removed
net0: name=eth0,ip=192.168.20.20/24,tag=20,type=veth
scsi1: /dev/disk/by-id/disk-serial-one,size=1T
"""


def router_snapshot() -> str:
    return """address=192.168.20.1/24 network=192.168.20.0 interface=VLAN20-MGMT
address=192.168.30.1/24 network=192.168.30.0 interface=VLAN30-SERVERS
name="dhcp-vlan20" interface=VLAN20-MGMT
name="dhcp-vlan30" interface=VLAN30-SERVERS
name="wifi1" type="wifi"
name="wifi1-guest" type="wifi"
"""


def write_snapshot(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def future_manifest_path() -> Path:
    return Path(__file__).parents[1] / "config" / "examples" / "future-state.yaml"


def test_parsers_keep_exact_identifiers_only_in_memory(tmp_path: Path) -> None:
    proxmox = parse_proxmox_snapshot(write_snapshot(tmp_path / "proxmox.txt", proxmox_snapshot()))
    router = parse_router_snapshot(write_snapshot(tmp_path / "router.txt", router_snapshot()))

    assert {guest.vm_id for guest in proxmox.guests} == {100, 22000}
    assert proxmox.raw_disk_ids == {"disk-serial-one"}
    assert {str(address) for address in proxmox.addresses} == {"192.168.20.20"}
    assert router.gateway_count == 2
    assert router.dhcp_server_count == 2
    assert router.wifi_interface_count == 2


@pytest.mark.parametrize(
    "secret_line",
    [
        'password="not-redacted"',
        "private-key=actual-private-value",
        "token: exposed-token-value",
    ],
)
def test_parser_refuses_secret_shaped_input(tmp_path: Path, secret_line: str) -> None:
    path = write_snapshot(tmp_path / "unsafe.txt", proxmox_snapshot() + secret_line)

    with pytest.raises(DiscoveryError, match="unredacted secret-shaped"):
        parse_proxmox_snapshot(path)


def test_parser_accepts_explicit_redaction_marker(tmp_path: Path) -> None:
    path = write_snapshot(tmp_path / "safe.txt", proxmox_snapshot() + 'password="<redacted>"')

    assert len(parse_proxmox_snapshot(path).guests) == 2


def test_read_only_evidence_passes_without_exposing_identifiers(tmp_path: Path) -> None:
    manifest = load_manifest(future_manifest_path())
    proxmox_path = write_snapshot(tmp_path / "proxmox.txt", proxmox_snapshot())
    router_path = write_snapshot(tmp_path / "router.txt", router_snapshot())
    output = tmp_path / "evidence.json"

    written = write_read_only_evidence(future_manifest_path(), proxmox_path, router_path, output)
    content = written.read_text(encoding="utf-8")
    evidence = json.loads(content)

    assert evidence["admission"] == "pass"
    assert evidence["production_mutation_performed"] is False
    assert evidence["protected_guest_count"] == 2
    assert manifest.digest in content
    assert "22000" not in content
    assert "disk-serial-one" not in content
    assert "192.168.20.20" not in content


def test_collision_evidence_reports_only_a_category(tmp_path: Path) -> None:
    manifest = load_manifest(future_manifest_path())
    proxmox = parse_proxmox_snapshot(
        write_snapshot(tmp_path / "proxmox.txt", proxmox_snapshot(vm_id=200))
    )
    router = parse_router_snapshot(write_snapshot(tmp_path / "router.txt", router_snapshot()))

    evidence = build_read_only_evidence(manifest, proxmox, router)

    assert evidence.admission == "refused"
    assert evidence.refusal_categories == ["vmid-collision"]


def test_collector_contains_multiline_redaction_and_fail_closed_gate() -> None:
    collector = (
        Path(__file__).parents[1] / "other_scripts" / "discovery" / "collect-existing-homelab.ps1"
    ).read_text(encoding="utf-8")

    assert "Assert-DiscoveryTextSafe" in collector
    assert "backslash-newline continuations" in collector
    assert "Refusing to write" in collector
