from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from textual.widgets import Button

from homelabctl.configuration import load_config
from homelabctl.operations import Operation, OperationResult
from homelabctl.ui import (
    ConfigurationPage,
    ConfirmDialog,
    ControlPlaneApp,
    CopyCommandDialog,
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

        await pilot.click("#operation-secrets-init")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)

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

        await pilot.click("#confirm-cancel")
        await pilot.pause()

    execute.assert_called_once_with("recovery-test", app.config_path)
