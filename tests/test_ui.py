from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from textual.widgets import Button, Input, RichLog, Static, TextArea

from homelabctl.configuration import load_config, save_config
from homelabctl.models import HomelabConfig, default_config
from homelabctl.operations import OPERATIONS, Operation, OperationResult
from homelabctl.ui import (
    ACTION_SECTIONS,
    ActivityCopyDialog,
    ConfigurationPage,
    ConfirmDialog,
    ControlPlaneApp,
    CopyCommandDialog,
    SecretInputDialog,
)


async def test_compact_layout_hides_sidebar(tmp_path: Path) -> None:
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(80, 24)):
        assert app.screen.has_class("-compact")
        assert not app.query_one("#sidebar").display


async def test_navigation_and_first_run_save(tmp_path: Path) -> None:
    config_path = tmp_path / "site.yaml"
    app = ControlPlaneApp(config_path)

    async with app.run_test(size=(140, 48)) as pilot:
        assert app.query_one("#pages").current == "overview"

        await pilot.press("2")
        await pilot.pause()
        assert app.query_one("#pages").current == "configuration"

        app.query_one("#field-site-name").value = "test-lab"
        app.query_one("#field-cloudflare-domains").value = "example.com, lab.example.net"
        app.query_one(ConfigurationPage).scroll_end(animate=False)
        await pilot.pause()
        app.query_one("#config-save", Button).press()
        await pilot.pause()

    config = load_config(config_path)
    assert config.site.name == "test-lab"
    assert config.cloudflare.domains == ["example.com", "lab.example.net"]


async def test_form_save_preserves_yaml_managed_resources(tmp_path: Path) -> None:
    config_path = tmp_path / "site.yaml"
    data = default_config().model_dump(mode="json")
    data["automation"]["ssh_public_keys"] = ["ssh-ed25519 AAAAC3NzaCTest automation"]
    data["proxmox"]["containers"] = [
        {
            "key": "dns",
            "vm_id": 110,
            "hostname": "dns",
            "template_file_id": "local:vztmpl/debian-13-standard.tar.zst",
            "address": "192.168.10.10/24",
        }
    ]
    data["cloudflare"] = {
        "domains": ["example.com"],
        "records": [
            {
                "zone": "example.com",
                "name": "app",
                "type": "A",
                "content": "1.1.1.1",
            }
        ],
    }
    original = HomelabConfig.model_validate(data)
    save_config(original, config_path)
    app = ControlPlaneApp(config_path)

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("2")
        await pilot.pause()
        app.query_one("#field-site-name", Input).value = "updated-lab"
        app.query_one(ConfigurationPage).scroll_end(animate=False)
        app.query_one("#config-save", Button).press()
        await pilot.pause()

    saved = load_config(config_path)
    assert saved.site.name == "updated-lab"
    assert saved.proxmox.containers == original.proxmox.containers
    assert saved.cloudflare.records == original.cloudflare.records
    assert saved.automation.ssh_public_keys == original.automation.ssh_public_keys


async def test_actions_are_grouped_in_meaningful_navigation_sections(tmp_path: Path) -> None:
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("4")
        assert app.query_one("#pages").current == "proxmox"
        assert app.query_one("#operation-proxmox-bootstrap", Button)

        await pilot.press("6")
        assert app.query_one("#pages").current == "maintenance"
        assert app.query_one("#operation-update", Button)

        await pilot.press("7")
        assert app.query_one("#pages").current == "diagnostics"
        assert app.query_one("#operation-doctor", Button)


async def test_successful_action_updates_step_section_and_overall_progress(
    tmp_path: Path, monkeypatch
) -> None:
    execute = Mock(return_value=OperationResult(True, "Validation", ("Validated",)))
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")
    total = sum(operation.visible for operation in OPERATIONS)

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("3")
        await pilot.click("#operation-validate")
        await pilot.pause()

        assert str(app.query_one("#status-validate", Static).content) == "✓ Completed"
        assert "1/" in str(app.query_one("#nav-setup", Button).label)
        overall = str(app.query_one("#overall-progress", Static).content)
        assert f"1/{total} complete" in overall


async def test_failed_action_is_marked_as_needing_attention(tmp_path: Path, monkeypatch) -> None:
    execute = Mock(return_value=OperationResult(False, "Validation", ("Invalid",)))
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("3")
        await pilot.click("#operation-validate")
        await pilot.pause()

        assert str(app.query_one("#status-validate", Static).content) == "! Attention"
        assert str(app.query_one("#nav-setup", Button).label).endswith("!")
        assert "1 attention" in str(app.query_one("#overall-progress", Static).content)


def test_visible_operation_sequences_are_unique_within_each_menu_section() -> None:
    for section in ACTION_SECTIONS:
        sequences = [
            operation.sequence
            for operation in OPERATIONS
            if operation.visible and operation.section == section
        ]
        assert sequences
        assert len(sequences) == len(set(sequences))


async def test_every_menu_renders_all_visible_actions_in_execution_order(tmp_path: Path) -> None:
    app = ControlPlaneApp(tmp_path / "site.yaml")
    page_keys = {
        "setup": "3",
        "proxmox": "4",
        "infrastructure": "5",
        "maintenance": "6",
        "diagnostics": "7",
    }

    async with app.run_test(size=(140, 48)) as pilot:
        for section, key in page_keys.items():
            await pilot.press(key)
            await pilot.pause()
            expected = [
                operation.identifier
                for operation in sorted(
                    (
                        operation
                        for operation in OPERATIONS
                        if operation.visible and operation.section == section
                    ),
                    key=lambda operation: (operation.sequence, operation.identifier),
                )
            ]
            buttons = app.query(f"#{section} .operation-card Button").results(Button)
            assert [
                button.id.removeprefix("operation-") for button in buttons if button.id
            ] == expected
            assert all(button.variant == "primary" for button in buttons)
            assert all(str(button.label) == "Run" for button in buttons)
            titles = app.query(f"#{section} .operation-title").results(Static)
            descriptions = app.query(f"#{section} .operation-description").results(Static)
            expected_operations = [
                operation
                for operation in sorted(
                    (
                        operation
                        for operation in OPERATIONS
                        if operation.visible and operation.section == section
                    ),
                    key=lambda operation: (operation.sequence, operation.identifier),
                )
            ]
            assert [str(title.content) for title in titles] == [
                f"{number}. {operation.title}"
                for number, operation in enumerate(expected_operations, start=1)
            ]
            assert [str(description.content) for description in descriptions] == [
                operation.description for operation in expected_operations
            ]
            assert all(str(description.content).strip() for description in descriptions)
            assert all(title.virtual_size.height <= title.size.height for title in titles)
            assert all(
                description.virtual_size.height <= description.size.height
                for description in descriptions
            )


async def test_compact_menu_stacks_every_infrastructure_action(tmp_path: Path) -> None:
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("5")
        await pilot.pause()
        buttons = app.query("#infrastructure .operation-card Button").results(Button)
        positions = [button.region.y for button in buttons]
        assert positions == sorted(positions)
        assert len(set(positions)) == len(positions)


async def test_changing_menu_operation_shows_plan_and_can_be_cancelled(
    tmp_path: Path, monkeypatch
) -> None:
    execute = Mock()
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        assert app.query_one("#operation-secrets-init")
        app.query_one("#operation-secrets-init", Button).press()
        await pilot.pause(0.2)
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.pause(0.05)

        await pilot.click("#confirm-cancel")
        await pilot.pause()

        assert str(app.query_one("#status-secrets-init", Static).content) == "○ Pending"

    execute.assert_not_called()


async def test_ssh_command_dialog_copies_primary_and_fallback_commands(tmp_path: Path) -> None:
    app = ControlPlaneApp(tmp_path / "site.yaml")
    primary = 'ssh-copy-id -i "/root/.ssh/proxmox_bootstrap_ed25519.pub" root@192.168.20.10'
    fallback = "install public key fallback"

    async with app.run_test(size=(140, 48)) as pilot:
        app.push_screen(CopyCommandDialog(primary, ("ssh-copy-id",), fallback))
        await pilot.pause()

        await pilot.click("#command-copy")
        assert app.clipboard == primary

        await pilot.click("#fallback-copy")
        assert app.clipboard == fallback

        await pilot.click("#command-close")
        await pilot.pause()


async def test_token_recovery_requires_a_second_explicit_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    operation = Operation(
        "recovery-test",
        "Bootstrap identity",
        "Test recovery flow",
        lambda path: OperationResult(True, "unused", ()),
    )
    initial = OperationResult(
        False,
        "Token recovery required",
        ("Existing token has no captured value",),
        recovery_operation="hidden-recovery",
        recovery_prompt="Delete only the named token and capture its replacement?",
    )
    execute = Mock(return_value=initial)
    monkeypatch.setattr("homelabctl.ui.OPERATIONS", (operation,))
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("3")
        await pilot.pause()
        await pilot.click("#operation-recovery-test")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.pause(0.05)

        await pilot.click("#confirm-cancel")
        await pilot.pause()

    execute.assert_called_once_with("recovery-test", app.config_path)


async def test_masked_cloudflare_token_is_passed_directly_to_secret_operation(
    tmp_path: Path, monkeypatch
) -> None:
    operation = Operation(
        "secret-test",
        "Set token",
        "Test masked token flow",
        lambda path: OperationResult(False, "unused", ()),
        destructive=True,
        plan=lambda path: OperationResult(True, "plan", ("Replace encrypted token",)),
        secret_prompt="Paste token",
    )
    execute_secret = Mock(return_value=OperationResult(True, "Set token", ("Saved",)))
    monkeypatch.setattr("homelabctl.ui.OPERATIONS", (operation,))
    monkeypatch.setattr("homelabctl.ui.execute_with_secret", execute_secret)
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("3")
        await pilot.click("#operation-secret-test")
        await pilot.pause(0.2)
        await pilot.click("#confirm-continue")
        await pilot.pause(0.2)
        assert isinstance(app.screen, SecretInputDialog)
        secret_input = app.screen.query_one("#secret-input-value", Input)
        assert secret_input.password
        secret_input.value = "private-token-value"
        await pilot.click("#secret-input-save")
        await pilot.pause()

    execute_secret.assert_called_once_with("secret-test", "private-token-value", app.config_path)


async def test_opentofu_operation_is_reachable_in_very_wide_layout(
    tmp_path: Path, monkeypatch
) -> None:
    execute = Mock(return_value=OperationResult(True, "OpenTofu", ("Validated",)))
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("5")
        await pilot.pause()
        first_action = app.query_one("#operation-automation-ssh", Button)
        assert app.query_one("#operation-tofu-apply", Button)
        assert app.query_one("#operation-ansible-check", Button)
        assert app.query_one("#operation-ansible-apply", Button)
        assert app.query_one("#operation-applications-check", Button)
        last_action = app.query_one("#operation-applications-apply", Button)
        assert last_action.region.y > first_action.region.y
        assert app.query_one("#infrastructure .actions-grid").virtual_size.height >= 15
        activity_log = app.query_one("#activity-log-infrastructure", RichLog)
        assert activity_log.region.x > first_action.region.x
        await pilot.click("#operation-tofu-check")
        await pilot.pause()

    execute.assert_called_once_with("tofu-check", app.config_path)


async def test_activity_can_be_copied_as_plain_text(tmp_path: Path, monkeypatch) -> None:
    execute = Mock(return_value=OperationResult(True, "OpenTofu", ("Validated",)))
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")
    app._clock = Mock(side_effect=[100.0, 100.0])

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("5")
        await pilot.click("#operation-tofu-check")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert isinstance(app.screen, ActivityCopyDialog)
        copy_text = app.screen.query_one("#activity-copy-text", TextArea)
        expected = (
            "> Check OpenTofu foundation\n"
            "Check OpenTofu foundation · started\n"
            "Check OpenTofu foundation · finished in 0s\n"
            "Validated\n"
            "Completed\n"
        )
        assert copy_text.text == expected
        assert copy_text.selected_text == expected
        assert (tmp_path / "logs" / "activity-report.txt").read_text(encoding="utf-8") == expected

        await pilot.click("#activity-copy-direct")
        await pilot.pause()
        assert app.clipboard == expected
