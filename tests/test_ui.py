from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from textual.widgets import Button

from homelabctl.configuration import load_config
from homelabctl.ui import ConfigurationPage, ConfirmDialog, ControlPlaneApp


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
