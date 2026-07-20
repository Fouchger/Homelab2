"""Typed, reusable site configuration models."""

from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv4Interface, IPv4Network, IPv6Address, ip_address
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    IPvAnyNetwork,
    field_validator,
    model_validator,
)

SITE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
TIMEZONE_PATTERN = re.compile(r"^[A-Za-z_+-]+(?:/[A-Za-z0-9_+.-]+)+$")
USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME_PATTERN = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
TEMPLATE_FILE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+:vztmpl/[A-Za-z0-9_.+~-]+$")
TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DNS_RECORD_NAME_PATTERN = re.compile(
    r"^(?:@|(?:\*\.)?(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?)"
    r"(?:\.[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?)*)$"
)
SSH_PUBLIC_KEY_TYPES = (
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)


def normalize_ssh_public_key(value: str) -> str:
    normalized = value.strip()
    if "\n" in normalized or "\r" in normalized:
        raise ValueError("SSH public keys must each fit on one line")
    parts = normalized.split()
    if len(parts) < 2 or parts[0] not in SSH_PUBLIC_KEY_TYPES:
        raise ValueError("enter OpenSSH-format public keys")
    return normalized


def normalize_domain(value: str, *, example: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not DOMAIN_PATTERN.fullmatch(normalized):
        raise ValueError(f"enter a valid DNS domain such as {example}")
    return normalized


class StrictModel(BaseModel):
    """Reject misspelled or obsolete settings instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, validate_default=True)


class SiteSettings(StrictModel):
    name: str = Field(default="homelab", description="Short identifier for this homelab")
    domain: str = Field(default="home.arpa", description="Internal DNS domain")
    timezone: str = Field(default="Pacific/Auckland", description="IANA timezone")
    environment: Literal["development", "staging", "production"] = "production"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("use 2-32 lowercase letters, numbers, or hyphens")
        return normalized

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return normalize_domain(value, example="home.arpa")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        if not TIMEZONE_PATTERN.fullmatch(normalized):
            raise ValueError("enter an IANA timezone such as Pacific/Auckland")
        return normalized


class ProxmoxLxcSettings(StrictModel):
    """One OpenTofu-owned, unprivileged Debian LXC guest."""

    key: str = Field(description="Stable resource key that survives list reordering")
    vm_id: int = Field(ge=100, le=999_999_999)
    hostname: str
    template_file_id: str = Field(description="Proxmox template ID such as local:vztmpl/x.tar.zst")
    address: IPv4Interface
    cores: int = Field(default=1, ge=1, le=128)
    memory_mb: int = Field(default=1024, ge=256, le=1_048_576)
    swap_mb: int = Field(default=512, ge=0, le=1_048_576)
    disk_gb: int = Field(default=8, ge=1, le=16_384)
    started: bool = True
    start_on_boot: bool = True
    nesting: bool = False
    protection: bool = False
    tags: list[str] = Field(default_factory=lambda: ["homelab"], max_length=20)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("use a stable 2-32 character lowercase key")
        return normalized

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not HOSTNAME_PATTERN.fullmatch(normalized):
            raise ValueError("enter a valid lowercase DNS hostname label")
        return normalized

    @field_validator("template_file_id")
    @classmethod
    def validate_template_file_id(cls, value: str) -> str:
        normalized = value.strip()
        if not TEMPLATE_FILE_PATTERN.fullmatch(normalized):
            raise ValueError("use a Proxmox template ID such as local:vztmpl/debian.tar.zst")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip().lower() for tag in value]
        if any(not TAG_PATTERN.fullmatch(tag) for tag in normalized):
            raise ValueError(
                "tags must contain only lowercase letters, numbers, dot, dash, or underscore"
            )
        if len(normalized) != len(set(normalized)):
            raise ValueError("tags must not contain duplicates")
        return sorted(normalized)


class ProxmoxSettings(StrictModel):
    api_url: AnyHttpUrl = "https://pve.home.arpa:8006"
    node: str = Field(default="pve", min_length=1, max_length=63)
    storage: str = Field(default="local-lvm", min_length=1, max_length=63)
    token_id: str = Field(
        default="homelab@pve!control-plane",
        description="Proxmox API token identifier; the secret is supplied separately",
    )
    verify_tls: bool = True
    containers: list[ProxmoxLxcSettings] = Field(default_factory=list, max_length=100)

    @field_validator("api_url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("the Proxmox API URL must use HTTPS")
        return value

    @field_validator("node", "storage", "token_id")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


class CloudflareDnsRecord(StrictModel):
    """One public DNS record exclusively owned by OpenTofu."""

    zone: str
    name: str = Field(description="Relative record name, or @ for the zone apex")
    type: Literal["A", "AAAA", "CNAME"]
    content: str
    ttl: int = 1
    proxied: bool = False

    @field_validator("zone")
    @classmethod
    def validate_zone(cls, value: str) -> str:
        return normalize_domain(value, example="example.com")

    @field_validator("name")
    @classmethod
    def validate_record_name(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not DNS_RECORD_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("use @ or a relative DNS name such as app or *.apps")
        return normalized

    @field_validator("ttl")
    @classmethod
    def validate_ttl(cls, value: int) -> int:
        if value != 1 and not 60 <= value <= 86_400:
            raise ValueError("TTL must be 1 for automatic or between 60 and 86400 seconds")
        return value

    @model_validator(mode="after")
    def validate_content_for_record_type(self) -> CloudflareDnsRecord:
        normalized = self.content.strip().lower().rstrip(".")
        if self.type in {"A", "AAAA"}:
            try:
                address = ip_address(normalized)
            except ValueError as exc:
                raise ValueError(f"{self.type} record content must be a valid IP address") from exc
            expected_type = IPv4Address if self.type == "A" else IPv6Address
            if not isinstance(address, expected_type):
                raise ValueError(f"{self.type} record content uses the wrong IP version")
            if not address.is_global:
                raise ValueError(f"{self.type} record content must be a public IP address")
            object.__setattr__(self, "content", str(address))
        else:
            object.__setattr__(
                self, "content", normalize_domain(normalized, example="target.example.net")
            )
        return self

    @property
    def fqdn(self) -> str:
        return self.zone if self.name == "@" else f"{self.name}.{self.zone}"

    @property
    def resource_key(self) -> str:
        return f"{self.zone}/{self.type}/{self.name}"


class CloudflareSettings(StrictModel):
    domains: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Public DNS domains managed through Cloudflare",
    )
    records: list[CloudflareDnsRecord] = Field(default_factory=list, max_length=500)

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        normalized = [normalize_domain(domain, example="example.com") for domain in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("domains must not contain duplicates")
        return normalized


class NetworkSettings(StrictModel):
    management_cidr: IPvAnyNetwork = "192.168.10.0/24"
    gateway: IPvAnyAddress = "192.168.10.1"
    dns_servers: list[IPvAnyAddress] = Field(
        default_factory=lambda: [IPv4Address("192.168.10.1")], min_length=1, max_length=4
    )
    bridge: str = Field(default="vmbr0", min_length=1, max_length=15)
    vlan_id: int | None = Field(default=None, ge=1, le=4094)

    @field_validator("management_cidr")
    @classmethod
    def require_ipv4_network(cls, value: IPvAnyNetwork) -> IPvAnyNetwork:
        if not isinstance(value, IPv4Network):
            raise ValueError("IPv6 management networks are not supported yet")
        return value

    @model_validator(mode="after")
    def gateway_must_be_usable(self) -> NetworkSettings:
        if not isinstance(self.gateway, IPv4Address):
            raise ValueError("the management gateway must be an IPv4 address")
        if self.gateway not in self.management_cidr:
            raise ValueError("the gateway must be inside the management network")
        if self.gateway in {
            self.management_cidr.network_address,
            self.management_cidr.broadcast_address,
        }:
            raise ValueError("the gateway must be a usable host address")
        return self


class AutomationSettings(StrictModel):
    ssh_user: str = "automation"
    ssh_private_key: str = "~/.ssh/homelab_ed25519"
    ssh_public_keys: list[str] = Field(default_factory=list, max_length=10)
    ssh_public_key_files: list[str] = Field(default_factory=list, max_length=10)
    become: bool = True

    @field_validator("ssh_user")
    @classmethod
    def validate_ssh_user(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("enter a valid Linux account name")
        return normalized

    @field_validator("ssh_private_key")
    @classmethod
    def validate_private_key_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("enter the path to a dedicated SSH private key")
        return normalized

    @field_validator("ssh_public_keys")
    @classmethod
    def validate_public_keys(cls, value: list[str]) -> list[str]:
        normalized = [normalize_ssh_public_key(key) for key in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("SSH public keys must not contain duplicates")
        return normalized

    @field_validator("ssh_public_key_files")
    @classmethod
    def validate_public_key_files(cls, value: list[str]) -> list[str]:
        normalized = [path.strip() for path in value]
        if any(not path or "\n" in path or "\r" in path for path in normalized):
            raise ValueError("SSH public key file paths must be non-empty single-line values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("SSH public key file paths must not contain duplicates")
        return normalized


class DeploymentSettings(StrictModel):
    channel: Literal["stable", "edge"] = "stable"
    check_interval_minutes: int = Field(default=60, ge=5, le=10080)
    automatic_updates: bool = False
    require_confirmation: bool = True


class ApplicationSettings(StrictModel):
    type: Literal["uptime-kuma", "technitium"]
    guest: str
    enabled: bool = True
    port: int = Field(default=3001, ge=1024, le=65535)
    credential: str | None = None

    @field_validator("guest")
    @classmethod
    def validate_guest(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("use an existing stable guest key")
        return normalized

    @field_validator("credential")
    @classmethod
    def validate_credential(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not SITE_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("use an encrypted credential key")
        return normalized

    @model_validator(mode="after")
    def require_application_settings(self) -> ApplicationSettings:
        if self.type == "technitium" and not self.credential:
            raise ValueError("Technitium requires an encrypted admin credential key")
        if self.type == "technitium" and self.port != 5380:
            raise ValueError("Technitium management must use its internal port 5380")
        if self.type == "uptime-kuma" and self.credential:
            raise ValueError("Uptime Kuma does not consume an installation credential")
        return self


class HomelabConfig(StrictModel):
    """Top-level, versioned configuration for one homelab site."""

    schema_version: Literal[1] = 1
    site: SiteSettings = Field(default_factory=SiteSettings)
    cloudflare: CloudflareSettings = Field(default_factory=CloudflareSettings)
    proxmox: ProxmoxSettings = Field(default_factory=ProxmoxSettings)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)
    deployment: DeploymentSettings = Field(default_factory=DeploymentSettings)
    applications: dict[str, ApplicationSettings] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def validate_managed_resources(self) -> HomelabConfig:
        containers = self.proxmox.containers
        for attribute, label in (
            ("key", "container keys"),
            ("vm_id", "container VM IDs"),
            ("hostname", "container hostnames"),
        ):
            values = [getattr(container, attribute) for container in containers]
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")

        addresses = [container.address.ip for container in containers]
        if len(addresses) != len(set(addresses)):
            raise ValueError("container management addresses must be unique")
        for container in containers:
            if container.address.network != self.network.management_cidr:
                raise ValueError(
                    f"container {container.key} address must use the management network and prefix"
                )
            if container.address.ip in {
                self.network.management_cidr.network_address,
                self.network.management_cidr.broadcast_address,
                self.network.gateway,
            }:
                raise ValueError(
                    f"container {container.key} address must be a usable, unreserved host"
                )
        if containers and not (
            self.automation.ssh_public_keys or self.automation.ssh_public_key_files
        ):
            raise ValueError(
                "at least one automation SSH public key or public key file is required for containers"
            )

        container_keys = {container.key for container in containers}
        for key, application in self.applications.items():
            if not SITE_NAME_PATTERN.fullmatch(key):
                raise ValueError(f"application key {key!r} must be a stable lowercase key")
            if application.guest not in container_keys:
                raise ValueError(f"application {key} targets unknown container {application.guest}")

        domain_set = set(self.cloudflare.domains)
        record_keys = [record.resource_key for record in self.cloudflare.records]
        if len(record_keys) != len(set(record_keys)):
            raise ValueError(
                "Cloudflare records must have unique zone, type, and name combinations"
            )
        for record in self.cloudflare.records:
            if record.zone not in domain_set:
                raise ValueError(
                    f"Cloudflare record zone {record.zone} is not in configured domains"
                )
            if record.name != "@" and _is_domain_or_subdomain(record.name, record.zone):
                raise ValueError("Cloudflare record names must be relative to their zone")
            if _is_domain_or_subdomain(record.fqdn, self.site.domain):
                raise ValueError("Cloudflare records cannot publish the internal site domain")
            if record.type == "CNAME" and _is_domain_or_subdomain(record.content, self.site.domain):
                raise ValueError("Cloudflare CNAME records cannot target the internal site domain")
        return self


def _is_domain_or_subdomain(candidate: str, domain: str) -> bool:
    return candidate == domain or candidate.endswith(f".{domain}")


def default_config() -> HomelabConfig:
    """Return safe example values for the first-run editor."""

    return HomelabConfig()
