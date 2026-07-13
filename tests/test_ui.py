from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from textual.widgets import Button, Input

from homelabctl.configuration import load_config
from homelabctl.operations import Operation, OperationResult
from homelabctl.ui import (
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
        await pilot.pause(0.05)
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.pause(0.05)

        await pilot.click("#confirm-cancel")
        await pilot.pause()

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
        await pilot.pause(0.05)
        await pilot.click("#confirm-continue")
        await pilot.pause(0.05)
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
        await pilot.click("#operation-tofu-check")
        await pilot.pause()

    execute.assert_called_once_with("tofu-check", app.config_path)


async def test_activity_can_be_copied_as_plain_text(tmp_path: Path, monkeypatch) -> None:
    execute = Mock(return_value=OperationResult(True, "OpenTofu", ("Validated",)))
    monkeypatch.setattr("homelabctl.ui.execute", execute)
    app = ControlPlaneApp(tmp_path / "site.yaml")

    async with app.run_test(size=(140, 48)) as pilot:
        await pilot.press("5")
        await pilot.click("#operation-tofu-check")
        await pilot.pause()
        await pilot.click("#copy-activity-infrastructure")

        assert app.clipboard == "> Check OpenTofu foundation\nValidated\nCompleted\n"
