from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from homelabctl.cli import main
from homelabctl.mikrotik import (
    MikroTikDesiredState,
    load_mikrotik_desired_state,
    write_mikrotik_proposal,
)
from homelabctl.operations import (
    OPERATIONS,
    check_router_change_readiness,
    router_configuration_status,
    validate_router_configuration,
)

EXAMPLE = Path(__file__).parents[1] / "config" / "examples" / "mikrotik-desired.yaml"
SITE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "site.yaml"


def example_data() -> dict[str, object]:
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def test_complete_router_example_validates() -> None:
    state = load_mikrotik_desired_state(EXAMPLE)

    assert state.router.validated_version == "7.23.2"
    assert {network.vlan_id for network in state.networks} == {20, 30, 40, 50, 60, 70, 90}
    assert state.identity.username == "admin"
    assert state.address_policy.static_last == 150
    assert state.address_policy.dhcp_first == 151
    assert state.dns.replacement_servers == state.dns.client_servers
    assert state.firewall.default_forward == "drop"
    assert not state.recovery.ready


def test_complete_vlan_set_is_required() -> None:
    data = example_data()
    data["networks"] = [item for item in data["networks"] if item["vlan_id"] != 90]

    with pytest.raises(ValidationError, match="complete internal VLAN set"):
        MikroTikDesiredState.model_validate(data)


def test_plaintext_wifi_password_is_rejected() -> None:
    data = example_data()
    data["wifi"][0]["password"] = "must-not-be-accepted"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MikroTikDesiredState.model_validate(data)


def test_router_management_cannot_be_broadened() -> None:
    data = example_data()
    data["firewall"]["allow_management_from"] = [20, 40]

    with pytest.raises(ValidationError, match="restricted to VLAN 20"):
        MikroTikDesiredState.model_validate(data)


def test_proposal_is_secret_free_hard_stopped_and_complete(tmp_path: Path) -> None:
    paths = write_mikrotik_proposal(EXAMPLE, tmp_path / "proposal")
    plan = json.loads(paths[0].read_text(encoding="utf-8"))
    candidate = paths[1].read_text(encoding="utf-8")
    matrix = paths[2].read_text(encoding="utf-8")

    assert plan["mode"] == "no-apply"
    assert plan["scope"]["internal_vlans"] == [20, 30, 40, 50, 60, 70, 90]
    assert plan["scope"]["static_range"] == ".1-.150"
    assert plan["scope"]["dhcp_range"] == ".151-.254"
    assert plan["scope"]["replacement_dns_servers"] == ["192.168.30.53"]
    assert plan["blocked_recovery_gates"] == [
        "credential_rotated",
        "encrypted_off_router_backup",
        "safe_mode_rehearsed",
        "rollback_rehearsed",
    ]
    assert candidate.splitlines()[2].startswith(":error")
    assert 'servers="192.168.30.53" allow-remote-requests=no' in candidate
    assert "interface=VLAN30-SERVERS" in candidate
    assert "H2 direct DNS 192.168.30.53 TCP" in candidate
    assert "final forward drop" in candidate
    assert "sops://" not in candidate
    assert "password" not in candidate.lower()
    assert all(f"| {vlan} |" in matrix for vlan in (20, 30, 40, 50, 60, 70, 90))


def test_cli_validates_and_renders_without_router_access(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["mikrotik", "validate", "--file", str(EXAMPLE)]) == 0
    assert "7 VLANs" in capsys.readouterr().out

    assert main(["mikrotik", "render", "--file", str(EXAMPLE), "--output", str(tmp_path)]) == 0
    assert "hard stop" in capsys.readouterr().out
    assert (tmp_path / "mikrotik-plan.json").is_file()


def test_router_menu_operations_are_safe_and_report_remaining_gates() -> None:
    status = router_configuration_status(SITE_CONFIG)
    validation = validate_router_configuration(SITE_CONFIG)
    readiness = check_router_change_readiness(SITE_CONFIG)

    assert status.succeeded
    assert "RouterOS 7.23.2 stable" in "\n".join(status.lines)
    assert "[PASS] wired management tested" in status.lines
    assert validation.succeeded
    assert "No router connection or configuration change was performed" in validation.lines
    assert not readiness.succeeded
    assert "Required: credential rotated" in readiness.lines
    assert "No Apply action is exposed until recovery and rollback are proven" in readiness.lines
    assert "router-apply" not in {operation.identifier for operation in OPERATIONS}
