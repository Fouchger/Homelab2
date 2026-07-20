"""Secret-free MikroTik desired-state validation and no-apply plan rendering."""

from __future__ import annotations

import json
import re
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MikroTikError(RuntimeError):
    """Raised when a MikroTik desired state or proposal cannot be produced safely."""


class MikroTikModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RouterTarget(MikroTikModel):
    model: Literal["hAP ax2"]
    release_channel: Literal["stable"] = "stable"
    validated_version: str
    minimum_version: str

    @field_validator("validated_version", "minimum_version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not re.fullmatch(r"7\.\d+(?:\.\d+)?", value.strip()):
            raise ValueError("use a RouterOS 7 version such as 7.23.2")
        return value.strip()


class RouterIdentity(MikroTikModel):
    username: Literal["admin"] = "admin"
    password_secret_ref: str
    ssh_public_key_file: str = "~/.ssh/homelab_router_ed25519.pub"

    @field_validator("password_secret_ref")
    @classmethod
    def require_password_secret_reference(cls, value: str) -> str:
        if value != "sops://credentials.router-admin.value":
            raise ValueError("router admin password must use the dedicated SOPS reference")
        return value


class RouterAddressPolicy(MikroTikModel):
    static_first: Literal[1] = 1
    static_last: Literal[150] = 150
    dhcp_first: Literal[151] = 151
    dhcp_last: Literal[254] = 254


class RecoveryGates(MikroTikModel):
    credential_rotated: bool = False
    fresh_secret_free_export: bool = False
    encrypted_off_router_backup: bool = False
    wired_management_tested: bool = False
    safe_mode_rehearsed: bool = False
    rollback_rehearsed: bool = False

    @property
    def ready(self) -> bool:
        return all(self.model_dump().values())


class PortPolicy(MikroTikModel):
    name: Literal["ether1", "ether2", "ether3", "ether4", "ether5"]
    role: Literal["wan", "trunk", "access"]
    tagged_vlans: list[int] = Field(default_factory=list)
    access_vlan: int | None = None
    recovery: bool = False

    @model_validator(mode="after")
    def validate_role(self) -> PortPolicy:
        if self.role == "trunk" and not self.tagged_vlans:
            raise ValueError("trunk ports require tagged_vlans")
        if self.role == "access" and self.access_vlan is None:
            raise ValueError("access ports require access_vlan")
        if self.role != "trunk" and self.tagged_vlans:
            raise ValueError("only trunk ports may declare tagged_vlans")
        if self.role != "access" and self.access_vlan is not None:
            raise ValueError("only access ports may declare access_vlan")
        if self.recovery and self.role != "access":
            raise ValueError("a recovery port must be an access port")
        return self


class NetworkPolicy(MikroTikModel):
    key: str
    vlan_id: int = Field(ge=10, le=4094)
    interface_name: str = Field(pattern=r"^VLAN\d{2,4}-[A-Z]+$")
    cidr: IPv4Network
    gateway: IPv4Address
    purpose: str = Field(min_length=3, max_length=100)
    dhcp: bool = True
    wifi_only: bool = False

    @model_validator(mode="after")
    def validate_network(self) -> NetworkPolicy:
        if self.cidr.prefixlen != 24:
            raise ValueError("MikroTik networks must use the approved /24 layout")
        if self.gateway not in self.cidr or int(str(self.gateway).split(".")[-1]) != 1:
            raise ValueError("the router gateway must be host .1 in its VLAN network")
        expected = int(str(self.cidr.network_address).split(".")[2])
        if self.vlan_id != expected:
            raise ValueError("VLAN ID must match the third address octet")
        return self


class WifiPolicy(MikroTikModel):
    key: str
    ssid: str = Field(min_length=1, max_length=32)
    band: Literal["2ghz", "5ghz"]
    vlan_id: int
    enabled: bool = True
    security_secret_ref: str

    @field_validator("security_secret_ref")
    @classmethod
    def require_secret_reference(cls, value: str) -> str:
        if not re.fullmatch(r"sops://credentials\.[a-z][a-z0-9-]{1,31}\.value", value):
            raise ValueError("Wi-Fi security must use a SOPS secret reference")
        return value


class DNSPolicy(MikroTikModel):
    client_mode: Literal["direct"] = "direct"
    existing_servers: list[IPv4Address] = Field(min_length=2, max_length=2)
    replacement_servers: list[IPv4Address] = Field(min_length=1, max_length=2)
    client_servers: list[IPv4Address] = Field(min_length=1, max_length=2)
    router_cache: Literal[False] = False

    @field_validator("existing_servers", "replacement_servers", "client_servers")
    @classmethod
    def unique_servers(cls, value: list[IPv4Address]) -> list[IPv4Address]:
        if len(value) != len(set(value)):
            raise ValueError("DNS servers must be unique")
        return value

    @model_validator(mode="after")
    def validate_cutover(self) -> DNSPolicy:
        if set(self.existing_servers) & set(self.replacement_servers):
            raise ValueError("replacement DNS addresses must not reuse existing DNS addresses")
        if self.client_servers != self.replacement_servers:
            raise ValueError("final client DNS must match the approved replacement servers")
        return self


class ServicePolicy(MikroTikModel):
    winbox: bool = True
    ssh: bool = True
    api: bool = False
    api_ssl: bool = False
    www: bool = False
    www_ssl: bool = False
    management_vlan: int = 20


class FirewallPolicy(MikroTikModel):
    default_input: Literal["drop"] = "drop"
    default_forward: Literal["drop"] = "drop"
    allow_internet_from: list[int]
    allow_management_from: list[int] = Field(default_factory=lambda: [20])
    log_final_drops: bool = True
    inbound_port_forwards: Literal[False] = False


class MikroTikDesiredState(MikroTikModel):
    schema_version: Literal[1] = 1
    router: RouterTarget
    identity: RouterIdentity
    address_policy: RouterAddressPolicy
    recovery: RecoveryGates
    ports: list[PortPolicy]
    networks: list[NetworkPolicy]
    wifi: list[WifiPolicy]
    dns: DNSPolicy
    firewall: FirewallPolicy
    services: ServicePolicy
    ntp_servers: list[str] = Field(min_length=2, max_length=4)
    wireguard_state: Literal["pending"] = "pending"

    @model_validator(mode="after")
    def validate_contract(self) -> MikroTikDesiredState:
        vlan_ids = [network.vlan_id for network in self.networks]
        if len(vlan_ids) != len(set(vlan_ids)):
            raise ValueError("network VLAN IDs must be unique")
        if set(vlan_ids) != {20, 30, 40, 50, 60, 70, 90}:
            raise ValueError("the complete internal VLAN set must be 20,30,40,50,60,70,90")
        interface_names = [network.interface_name for network in self.networks]
        if len(interface_names) != len(set(interface_names)):
            raise ValueError("network interface names must be unique")
        port_names = [port.name for port in self.ports]
        if len(port_names) != len(set(port_names)) or set(port_names) != {
            "ether1",
            "ether2",
            "ether3",
            "ether4",
            "ether5",
        }:
            raise ValueError("all five physical ports require exactly one policy")
        if not any(port.recovery and port.access_vlan == 20 for port in self.ports):
            raise ValueError("VLAN 20 requires a dedicated wired recovery access port")
        declared = set(vlan_ids)
        for port in self.ports:
            if set(port.tagged_vlans) - declared or (
                port.access_vlan is not None and port.access_vlan not in declared
            ):
                raise ValueError(f"port {port.name} references an unknown internal VLAN")
        for wifi in self.wifi:
            if wifi.vlan_id not in declared:
                raise ValueError(f"Wi-Fi {wifi.key} references an unknown VLAN")
        if set(self.firewall.allow_internet_from) != declared:
            raise ValueError("internet policy must explicitly cover every internal VLAN")
        if set(self.firewall.allow_management_from) != {20}:
            raise ValueError("router management must remain restricted to VLAN 20")
        if self.services.management_vlan != 20:
            raise ValueError("management services must remain restricted to VLAN 20")
        server_network = next(network for network in self.networks if network.vlan_id == 30)
        all_dns = {
            *self.dns.existing_servers,
            *self.dns.replacement_servers,
            *self.dns.client_servers,
        }
        if any(server not in server_network.cidr for server in all_dns):
            raise ValueError("all DNS servers must be in the servers VLAN")
        return self


def load_mikrotik_desired_state(path: str | Path) -> MikroTikDesiredState:
    desired_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(desired_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MikroTikError(f"Unable to read MikroTik desired state: {desired_path}") from exc
    if not isinstance(raw, dict):
        raise MikroTikError("MikroTik desired-state root must be a YAML mapping")
    try:
        return MikroTikDesiredState.model_validate(raw)
    except ValueError as exc:
        raise MikroTikError(f"MikroTik desired-state validation failed: {exc}") from exc


def _candidate_script(state: MikroTikDesiredState) -> str:
    dns = ",".join(str(server) for server in state.dns.client_servers)
    lines = [
        "# Homelab2 RouterOS candidate - REVIEW ONLY",
        "# Intentionally blocked: remove nothing and do not import this file.",
        ':error "NO-APPLY candidate: recovery approval and live-state diff are required"',
        "",
        "# Candidate non-secret policy follows after the hard stop.",
        f'/ip dns set servers="{dns}" allow-remote-requests=no',
        '/interface list add name=HOMELAB_INTERNAL comment="Homelab2 desired state"',
    ]
    for network in state.networks:
        lines.append(
            f"/interface list member add list=HOMELAB_INTERNAL interface={network.interface_name}"
        )
    dns_rules = []
    for server in state.dns.client_servers:
        for protocol in ("udp", "tcp"):
            dns_rules.append(
                "/ip firewall filter add chain=forward action=accept "
                f"in-interface-list=HOMELAB_INTERNAL dst-address={server} "
                f'protocol={protocol} dst-port=53 comment="H2 direct DNS {server} {protocol.upper()}"'
            )
    lines.extend(
        [
            '/ip firewall filter add chain=input action=accept connection-state=established,related comment="H2 input established"',
            '/ip firewall filter add chain=input action=drop connection-state=invalid comment="H2 input invalid"',
            '/ip firewall filter add chain=input action=accept protocol=icmp comment="H2 input ICMP"',
            '/ip firewall filter add chain=input action=accept in-interface-list=HOMELAB_INTERNAL protocol=udp dst-port=67 comment="H2 DHCP server"',
            '/ip firewall filter add chain=input action=accept in-interface=VLAN20-MGMT comment="H2 management only"',
            '/ip firewall filter add chain=input action=drop log=yes log-prefix="H2-IN-DROP " comment="H2 final input drop"',
            '/ip firewall filter add chain=forward action=accept connection-state=established,related comment="H2 forward established"',
            '/ip firewall filter add chain=forward action=drop connection-state=invalid comment="H2 forward invalid"',
            '/ip firewall filter add chain=forward action=accept in-interface=VLAN20-MGMT out-interface-list=HOMELAB_INTERNAL comment="H2 management to internal"',
            *dns_rules,
            '/ip firewall filter add chain=forward action=accept in-interface-list=HOMELAB_INTERNAL out-interface-list=WAN comment="H2 explicit internet"',
            '/ip firewall filter add chain=forward action=drop log=yes log-prefix="H2-FWD-DROP " comment="H2 final forward drop"',
            '/ip firewall nat add chain=srcnat action=masquerade out-interface-list=WAN comment="H2 WAN masquerade"',
            "/ip service set api disabled=yes",
            "/ip service set api-ssl disabled=yes",
            "/ip service set www disabled=yes",
            "/ip service set www-ssl disabled=yes",
            "/ip service set winbox disabled=no address=192.168.20.0/24",
            "/ip service set ssh disabled=no address=192.168.20.0/24",
            "",
            "# Wi-Fi security and WireGuard are intentionally not rendered from plaintext.",
            "# DHCP pool migration is intentionally deferred until lease admission is complete.",
        ]
    )
    return "\n".join(lines) + "\n"


def _validation_matrix(state: MikroTikDesiredState) -> str:
    rows = [
        "# MikroTik acceptance matrix",
        "",
        "Run only after a reviewed Safe Mode change window. Record pass/fail and evidence.",
        "",
        "| VLAN | Purpose | Gateway | DHCP | DNS UDP/TCP | Internet | Isolation |",
        "|---:|---|---|---|---|---|---|",
    ]
    for network in state.networks:
        rows.append(
            f"| {network.vlan_id} | {network.purpose} | {network.gateway} | "
            "Pending | Pending | Pending | Pending |"
        )
    rows.extend(
        [
            "",
            "Additional gates: wired VLAN 20 management, Winbox/SSH restriction, both Wi-Fi bands,",
            "NTP sync, reboot persistence, rollback, and direct DNS failure behaviour.",
        ]
    )
    return "\n".join(rows) + "\n"


def write_mikrotik_proposal(state_path: str | Path, output: str | Path) -> list[Path]:
    """Write a secret-free, hard-stopped proposal; never contact or mutate a router."""

    state = load_mikrotik_desired_state(state_path)
    output_path = Path(output).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": 1,
        "mode": "no-apply",
        "router": state.router.model_dump(),
        "router_identity": {
            "username": state.identity.username,
            "password_source": "SOPS reference (value never rendered)",
            "ssh_public_key_file": state.identity.ssh_public_key_file,
        },
        "recovery_ready": state.recovery.ready,
        "blocked_recovery_gates": [
            name for name, ready in state.recovery.model_dump().items() if not ready
        ],
        "scope": {
            "ports": len(state.ports),
            "internal_vlans": [network.vlan_id for network in state.networks],
            "wifi_networks": len(state.wifi),
            "static_range": ".1-.150",
            "dhcp_range": ".151-.254",
            "dns_mode": state.dns.client_mode,
            "existing_dns_servers_to_retire": [
                str(server) for server in state.dns.existing_servers
            ],
            "replacement_dns_servers": [str(server) for server in state.dns.replacement_servers],
            "default_input": state.firewall.default_input,
            "default_forward": state.firewall.default_forward,
            "wireguard": state.wireguard_state,
        },
        "deferred": [
            "DHCP range migration until live leases and static assignments are admitted",
            "Wi-Fi security material until SOPS-backed apply support exists",
            "WireGuard until endpoint, peers, and encrypted keys are approved",
            "live application until a current export is diffed and rollback is reviewed",
        ],
    }
    paths = [
        output_path / "mikrotik-plan.json",
        output_path / "mikrotik-candidate-NO-APPLY.rsc",
        output_path / "mikrotik-validation-matrix.md",
    ]
    paths[0].write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8", newline="\n")
    paths[1].write_text(_candidate_script(state), encoding="utf-8", newline="\n")
    paths[2].write_text(_validation_matrix(state), encoding="utf-8", newline="\n")
    return paths
