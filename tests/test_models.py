from __future__ import annotations

import pytest
from pydantic import ValidationError

from homelabctl.models import HomelabConfig, default_config


def test_default_configuration_is_valid() -> None:
    config = default_config()

    assert config.schema_version == 1
    assert config.site.name == "homelab"
    assert config.cloudflare.domains == []
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
