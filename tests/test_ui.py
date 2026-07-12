from __future__ import annotations

from pathlib import Path

from homelabctl.configuration import load_config
from homelabctl.ui import ConfigurationPage, ControlPlaneApp


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
        app.query_one(ConfigurationPage).scroll_end(animate=False)
        await pilot.pause()
        await pilot.click("#config-save")
        await pilot.pause()

    assert load_config(config_path).site.name == "test-lab"
