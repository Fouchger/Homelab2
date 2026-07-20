from __future__ import annotations

import pytest
from pydantic import ValidationError

from homelabctl.models import HomelabConfig, default_config


def test_dns_core_site_example_is_valid_and_secret_free() -> None:
    from pathlib import Path

    import yaml

    source = Path(__file__).parents[1] / "config" / "examples" / "dns-core-site.yaml"
    raw = source.read_text(encoding="utf-8")
    config = HomelabConfig.model_validate(yaml.safe_load(raw))

    assert config.proxmox.containers[0].vm_id == 220
    assert str(config.proxmox.containers[0].address) == "192.168.30.53/24"
    assert config.applications["technitium"].credential == "technitium-admin"
    assert "password" not in raw.lower()


def test_technitium_requires_credential_and_port_5380() -> None:
    with pytest.raises(ValidationError, match="encrypted admin credential"):
        HomelabConfig.model_validate(
            {"applications": {"technitium": {"type": "technitium", "guest": "dns-core01"}}}
        )


def test_default_configuration_is_valid() -> None:
    config = default_config()

    assert config.schema_version == 1
    assert config.site.name == "homelab"
    assert config.cloudflare.domains == []
    assert config.cloudflare.records == []
    assert config.proxmox.containers == []
    assert str(config.network.management_cidr) == "192.168.10.0/24"


def test_one_or_many_cloudflare_domains_are_normalized() -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"]["domains"] = ["Example.COM.", "lab.example.net"]

    config = HomelabConfig.model_validate(data)

    assert config.cloudflare.domains == ["example.com", "lab.example.net"]


def test_duplicate_cloudflare_domains_are_rejected() -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"]["domains"] = ["example.com", "EXAMPLE.COM."]

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        HomelabConfig.model_validate(data)


def test_invalid_cloudflare_domain_is_rejected() -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"]["domains"] = ["not a domain"]

    with pytest.raises(ValidationError, match="valid DNS domain"):
        HomelabConfig.model_validate(data)


def test_gateway_must_be_inside_management_network() -> None:
    data = default_config().model_dump(mode="json")
    data["network"]["gateway"] = "10.20.30.1"

    with pytest.raises(ValidationError, match="gateway must be inside"):
        HomelabConfig.model_validate(data)


def test_unknown_keys_are_rejected() -> None:
    data = default_config().model_dump(mode="json")
    data["proxmox"]["pasword"] = "a misspelled secret field"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HomelabConfig.model_validate(data)


def test_proxmox_url_requires_https() -> None:
    data = default_config().model_dump(mode="json")
    data["proxmox"]["api_url"] = "http://pve.home.arpa:8006"

    with pytest.raises(ValidationError, match="must use HTTPS"):
        HomelabConfig.model_validate(data)


def _configuration_with_container() -> dict[str, object]:
    data = default_config().model_dump(mode="json")
    data["automation"]["ssh_public_keys"] = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest"]
    data["proxmox"]["containers"] = [
        {
            "key": "dns-primary",
            "vm_id": 110,
            "hostname": "dns-primary",
            "template_file_id": "local:vztmpl/debian-13-standard.tar.zst",
            "address": "192.168.10.10/24",
            "cores": 2,
            "memory_mb": 1024,
            "swap_mb": 512,
            "disk_gb": 8,
            "started": True,
            "start_on_boot": True,
            "nesting": False,
            "protection": False,
            "tags": ["dns", "homelab"],
        }
    ]
    return data


def test_valid_proxmox_container_is_normalized() -> None:
    config = HomelabConfig.model_validate(_configuration_with_container())

    container = config.proxmox.containers[0]
    assert container.key == "dns-primary"
    assert str(container.address) == "192.168.10.10/24"
    assert container.tags == ["dns", "homelab"]


@pytest.mark.parametrize("field", ["key", "vm_id", "hostname", "address"])
def test_duplicate_proxmox_container_identity_is_rejected(field: str) -> None:
    data = _configuration_with_container()
    duplicate = dict(data["proxmox"]["containers"][0])
    duplicate.update(
        {
            "key": "dns-secondary",
            "vm_id": 111,
            "hostname": "dns-secondary",
            "address": "192.168.10.11/24",
        }
    )
    duplicate[field] = data["proxmox"]["containers"][0][field]
    data["proxmox"]["containers"].append(duplicate)

    with pytest.raises(ValidationError, match="must be unique"):
        HomelabConfig.model_validate(data)


def test_container_requires_management_address_and_public_key() -> None:
    data = _configuration_with_container()
    data["proxmox"]["containers"][0]["address"] = "192.168.20.10/24"

    with pytest.raises(ValidationError, match="must use the management network"):
        HomelabConfig.model_validate(data)

    data = _configuration_with_container()
    data["automation"]["ssh_public_keys"] = []

    with pytest.raises(ValidationError, match="SSH public key"):
        HomelabConfig.model_validate(data)

    data["automation"]["ssh_public_key_files"] = ["~/.ssh/homelab_ed25519.pub"]
    config = HomelabConfig.model_validate(data)
    assert config.automation.ssh_public_key_files == ["~/.ssh/homelab_ed25519.pub"]


def test_public_cloudflare_records_are_normalized() -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"] = {
        "domains": ["Example.COM."],
        "records": [
            {
                "zone": "Example.COM.",
                "name": "App",
                "type": "A",
                "content": "1.1.1.1",
                "ttl": 1,
                "proxied": False,
            },
            {
                "zone": "example.com",
                "name": "WWW",
                "type": "CNAME",
                "content": "App.Example.com.",
                "ttl": 300,
                "proxied": True,
            },
        ],
    }

    config = HomelabConfig.model_validate(data)

    assert config.cloudflare.records[0].fqdn == "app.example.com"
    assert config.cloudflare.records[1].content == "app.example.com"


def test_cloudflare_record_names_are_relative_and_may_use_service_labels() -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "_acme-challenge",
                "type": "CNAME",
                "content": "validation.example.net",
            }
        ],
    }

    config = HomelabConfig.model_validate(data)
    assert config.cloudflare.records[0].fqdn == "_acme-challenge.example.com"

    data["cloudflare"]["records"][0]["name"] = "app.example.com"
    with pytest.raises(ValidationError, match="must be relative"):
        HomelabConfig.model_validate(data)


def test_cloudflare_record_zone_must_be_configured() -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"]["records"] = [
        {
            "zone": "example.com",
            "name": "app",
            "type": "A",
            "content": "1.1.1.1",
        }
    ]

    with pytest.raises(ValidationError, match="not in configured domains"):
        HomelabConfig.model_validate(data)


def test_duplicate_and_internal_cloudflare_records_are_rejected() -> None:
    data = default_config().model_dump(mode="json")
    data["site"]["domain"] = "internal.example.com"
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "internal",
                "type": "CNAME",
                "content": "router.home.arpa",
            }
        ],
    }

    with pytest.raises(ValidationError, match="cannot publish the internal site domain"):
        HomelabConfig.model_validate(data)

    data["site"]["domain"] = "home.arpa"
    data["cloudflare"]["records"].append(dict(data["cloudflare"]["records"][0]))

    with pytest.raises(ValidationError, match="unique zone, type, and name"):
        HomelabConfig.model_validate(data)


@pytest.mark.parametrize(
    ("record_type", "content", "message"),
    [
        ("A", "192.168.10.4", "public IP address"),
        ("A", "2606:4700:4700::1111", "wrong IP version"),
        ("AAAA", "1.1.1.1", "wrong IP version"),
        ("CNAME", "router.home.arpa", "internal site domain"),
    ],
)
def test_cloudflare_record_content_is_safe(record_type: str, content: str, message: str) -> None:
    data = default_config().model_dump(mode="json")
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "app",
                "type": record_type,
                "content": content,
            }
        ],
    }

    with pytest.raises(ValidationError, match=message):
        HomelabConfig.model_validate(data)
