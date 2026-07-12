"""Typed, reusable site configuration models."""

from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv4Network
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
        normalized = value.strip().lower().rstrip(".")
        if not DOMAIN_PATTERN.fullmatch(normalized):
            raise ValueError("enter a valid DNS domain such as home.arpa")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        if not TIMEZONE_PATTERN.fullmatch(normalized):
            raise ValueError("enter an IANA timezone such as Pacific/Auckland")
        return normalized


class ProxmoxSettings(StrictModel):
    api_url: AnyHttpUrl = "https://pve.home.arpa:8006"
    node: str = Field(default="pve", min_length=1, max_length=63)
    storage: str = Field(default="local-lvm", min_length=1, max_length=63)
    token_id: str = Field(
        default="homelab@pve!control-plane",
        description="Proxmox API token identifier; the secret is supplied separately",
    )
    verify_tls: bool = True

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


class DeploymentSettings(StrictModel):
    channel: Literal["stable", "edge"] = "stable"
    check_interval_minutes: int = Field(default=60, ge=5, le=10080)
    automatic_updates: bool = False
    require_confirmation: bool = True


class HomelabConfig(StrictModel):
    """Top-level, versioned configuration for one homelab site."""

    schema_version: Literal[1] = 1
    site: SiteSettings = Field(default_factory=SiteSettings)
    proxmox: ProxmoxSettings = Field(default_factory=ProxmoxSettings)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)
    deployment: DeploymentSettings = Field(default_factory=DeploymentSettings)


def default_config() -> HomelabConfig:
    """Return safe example values for the first-run editor."""

    return HomelabConfig()
