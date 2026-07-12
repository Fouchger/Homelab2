"""Professional terminal control panel built with Textual."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    Switch,
)

from homelabctl.configuration import ConfigurationError, load_config, save_config
from homelabctl.doctor import run_checks
from homelabctl.models import HomelabConfig, default_config
from homelabctl.operations import OPERATIONS, OperationResult, execute


class ConfirmDialog(ModalScreen[bool]):
    """Reusable guard for operations that change or destroy infrastructure."""

    def __init__(self, title: str, detail: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.dialog_title, classes="dialog-title")
            yield Static(self.detail, classes="dialog-detail")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="confirm-cancel")
                yield Button("Continue", id="confirm-continue", variant="error")

    @on(Button.Pressed, "#confirm-cancel")
    def cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-continue")
    def confirm(self) -> None:
        self.dismiss(True)


class OverviewPage(VerticalScroll):
    def __init__(self, config_path: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        yield Static("Control plane overview", classes="page-title")
        yield Static(
            "One place to configure, validate, and safely operate this homelab.",
            classes="page-subtitle",
        )
        with Grid(id="status-grid"):
            with Vertical(classes="status-card"):
                yield Static("SITE CONFIGURATION", classes="eyebrow")
                yield Static("Checking", id="overview-config-value", classes="metric")
                yield Static(str(self.config_path), id="overview-config-detail", classes="muted")
            with Vertical(classes="status-card"):
                yield Static("TOOLCHAIN", classes="eyebrow")
                yield Static("Checking", id="overview-tools-value", classes="metric")
                yield Static("Required control-plane tools", classes="muted")
            with Vertical(classes="status-card"):
                yield Static("DEPLOYMENT SAFETY", classes="eyebrow")
                yield Static("Confirmation on", id="overview-safety-value", classes="metric")
                yield Static(
                    "Automatic apply is disabled", id="overview-safety-detail", classes="muted"
                )
        yield Static("Quick actions", classes="section-title")
        with Horizontal(classes="quick-actions"):
            yield Button("Edit configuration", id="quick-config", variant="primary")
            yield Button("Validate", id="quick-validate")
            yield Button("Run readiness check", id="quick-doctor")
        yield Static("Deployment modules", classes="section-title")
        yield Static(
            "OpenTofu provisioning and Ansible deployment actions will appear in Operations "
            "as those modules are added. The control panel only exposes implemented actions.",
            classes="notice",
        )

    def refresh_status(self) -> None:
        try:
            config = load_config(self.config_path)
        except ConfigurationError:
            self.query_one("#overview-config-value", Static).update("Needs setup")
            self.query_one("#overview-config-value", Static).add_class("metric-warning")
        else:
            value = self.query_one("#overview-config-value", Static)
            value.update(f"{config.site.name} · {config.site.environment}")
            value.remove_class("metric-warning")
            self.query_one("#overview-safety-value", Static).update(
                "Confirmation on" if config.deployment.require_confirmation else "Confirmation off"
            )
            self.query_one("#overview-safety-detail", Static).update(
                "Automatic updates enabled"
                if config.deployment.automatic_updates
                else "Automatic updates disabled"
            )

        checks = run_checks(self.config_path)
        tool_checks = checks[3:-1]
        present = sum(check.status == "pass" for check in tool_checks)
        self.query_one("#overview-tools-value", Static).update(
            f"{present}/{len(tool_checks)} available"
        )


class ConfigurationPage(VerticalScroll):
    class Saved(Message):
        def __init__(self, config: HomelabConfig) -> None:
            super().__init__()
            self.config = config

    def __init__(self, config_path: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.config_path = config_path

    @staticmethod
    def field(label: str, identifier: str, placeholder: str = "") -> tuple[Label, Input]:
        return Label(label, classes="field-label"), Input(id=identifier, placeholder=placeholder)

    def compose(self) -> ComposeResult:
        yield Static("Site configuration", classes="page-title")
        yield Static(
            "Values are validated before an atomic save. Credentials are managed separately.",
            classes="page-subtitle",
        )
        with Vertical(classes="form-section"):
            yield Static("Identity", classes="section-title")
            for widget in self.field("Site name", "field-site-name", "my-homelab"):
                yield widget
            for widget in self.field("Internal domain", "field-domain", "home.arpa"):
                yield widget
            for widget in self.field("Timezone", "field-timezone", "Pacific/Auckland"):
                yield widget
            yield Label("Environment", classes="field-label")
            yield Select(
                [
                    ("Development", "development"),
                    ("Staging", "staging"),
                    ("Production", "production"),
                ],
                id="field-environment",
                allow_blank=False,
            )
        with Vertical(classes="form-section"):
            yield Static("Proxmox", classes="section-title")
            for widget in self.field("API URL", "field-api-url", "https://pve.home.arpa:8006"):
                yield widget
            for widget in self.field("Node", "field-node", "pve"):
                yield widget
            for widget in self.field("Storage", "field-storage", "local-lvm"):
                yield widget
            for widget in self.field("API token ID", "field-token-id", "user@realm!token"):
                yield widget
            with Horizontal(classes="switch-row"):
                yield Label("Verify TLS certificate")
                yield Switch(id="field-verify-tls")
        with Vertical(classes="form-section"):
            yield Static("Management network", classes="section-title")
            for widget in self.field("Network CIDR", "field-cidr", "192.168.10.0/24"):
                yield widget
            for widget in self.field("Gateway", "field-gateway", "192.168.10.1"):
                yield widget
            for widget in self.field(
                "DNS servers (comma separated)", "field-dns", "192.168.10.1, 1.1.1.1"
            ):
                yield widget
            for widget in self.field("Proxmox bridge", "field-bridge", "vmbr0"):
                yield widget
            for widget in self.field("VLAN ID (optional)", "field-vlan", ""):
                yield widget
        with Vertical(classes="form-section"):
            yield Static("Automation", classes="section-title")
            for widget in self.field("SSH user", "field-ssh-user", "automation"):
                yield widget
            for widget in self.field(
                "SSH private key path", "field-ssh-key", "~/.ssh/homelab_ed25519"
            ):
                yield widget
            with Horizontal(classes="switch-row"):
                yield Label("Use privilege escalation")
                yield Switch(id="field-become")
        with Vertical(classes="form-section"):
            yield Static("Control-plane updates", classes="section-title")
            yield Label("Release channel", classes="field-label")
            yield Select(
                [("Stable", "stable"), ("Edge", "edge")], id="field-channel", allow_blank=False
            )
            for widget in self.field("Check interval (minutes)", "field-interval", "60"):
                yield widget
            with Horizontal(classes="switch-row"):
                yield Label("Install approved updates automatically")
                yield Switch(id="field-auto-updates")
            with Horizontal(classes="switch-row"):
                yield Label("Require confirmation for changes")
                yield Switch(id="field-confirmation")
        yield Static("", id="config-feedback")
        with Horizontal(classes="form-actions"):
            yield Button("Reload", id="config-reload")
            yield Button("Validate and save", id="config-save", variant="success")

    def on_mount(self) -> None:
        self.load_into_form()

    def load_into_form(self) -> None:
        try:
            config = load_config(self.config_path)
            message = f"Loaded {self.config_path}"
        except ConfigurationError:
            config = default_config()
            message = "Using safe defaults. Review every value before saving."

        values = {
            "#field-site-name": config.site.name,
            "#field-domain": config.site.domain,
            "#field-timezone": config.site.timezone,
            "#field-api-url": str(config.proxmox.api_url),
            "#field-node": config.proxmox.node,
            "#field-storage": config.proxmox.storage,
            "#field-token-id": config.proxmox.token_id,
            "#field-cidr": str(config.network.management_cidr),
            "#field-gateway": str(config.network.gateway),
            "#field-dns": ", ".join(str(item) for item in config.network.dns_servers),
            "#field-bridge": config.network.bridge,
            "#field-vlan": "" if config.network.vlan_id is None else str(config.network.vlan_id),
            "#field-ssh-user": config.automation.ssh_user,
            "#field-ssh-key": str(config.automation.ssh_private_key),
            "#field-interval": str(config.deployment.check_interval_minutes),
        }
        for selector, value in values.items():
            self.query_one(selector, Input).value = value
        self.query_one("#field-environment", Select).value = config.site.environment
        self.query_one("#field-channel", Select).value = config.deployment.channel
        self.query_one("#field-verify-tls", Switch).value = config.proxmox.verify_tls
        self.query_one("#field-become", Switch).value = config.automation.become
        self.query_one("#field-auto-updates", Switch).value = config.deployment.automatic_updates
        self.query_one("#field-confirmation", Switch).value = config.deployment.require_confirmation
        self.set_feedback(message, error=False)

    def collect(self) -> HomelabConfig:
        value = lambda selector: self.query_one(selector, Input).value.strip()  # noqa: E731
        vlan = value("#field-vlan")
        data = {
            "schema_version": 1,
            "site": {
                "name": value("#field-site-name"),
                "domain": value("#field-domain"),
                "timezone": value("#field-timezone"),
                "environment": self.query_one("#field-environment", Select).value,
            },
            "proxmox": {
                "api_url": value("#field-api-url"),
                "node": value("#field-node"),
                "storage": value("#field-storage"),
                "token_id": value("#field-token-id"),
                "verify_tls": self.query_one("#field-verify-tls", Switch).value,
            },
            "network": {
                "management_cidr": value("#field-cidr"),
                "gateway": value("#field-gateway"),
                "dns_servers": [
                    item.strip() for item in value("#field-dns").split(",") if item.strip()
                ],
                "bridge": value("#field-bridge"),
                "vlan_id": int(vlan) if vlan else None,
            },
            "automation": {
                "ssh_user": value("#field-ssh-user"),
                "ssh_private_key": value("#field-ssh-key"),
                "become": self.query_one("#field-become", Switch).value,
            },
            "deployment": {
                "channel": self.query_one("#field-channel", Select).value,
                "check_interval_minutes": value("#field-interval"),
                "automatic_updates": self.query_one("#field-auto-updates", Switch).value,
                "require_confirmation": self.query_one("#field-confirmation", Switch).value,
            },
        }
        return HomelabConfig.model_validate(data)

    def set_feedback(self, message: str, *, error: bool) -> None:
        feedback = self.query_one("#config-feedback", Static)
        feedback.update(message)
        feedback.set_class(error, "feedback-error")
        feedback.set_class(not error, "feedback-success")

    @on(Button.Pressed, "#config-reload")
    def reload_form(self) -> None:
        self.load_into_form()

    @on(Button.Pressed, "#config-save")
    def save_form(self) -> None:
        try:
            config = self.collect()
            saved_path = save_config(config, self.config_path)
        except (ValidationError, ValueError, ConfigurationError) as exc:
            if isinstance(exc, ValidationError):
                issues = [
                    f"{'.'.join(str(p) for p in item['loc'])}: {item['msg'].removeprefix('Value error, ')}"
                    for item in exc.errors(include_url=False)
                ]
                message = "Please correct:\n" + "\n".join(f"• {item}" for item in issues)
            else:
                message = str(exc)
            self.set_feedback(message, error=True)
            self.app.notify("Configuration was not saved", severity="error")
            return
        self.set_feedback(f"Saved and validated {saved_path}", error=False)
        self.app.notify("Configuration saved", severity="information")
        self.post_message(self.Saved(config))


class OperationsPage(Vertical):
    def compose(self) -> ComposeResult:
        yield Static("Operations", classes="page-title")
        yield Static(
            "Run audited control-plane actions. Results remain visible in this session.",
            classes="page-subtitle",
        )
        with Grid(id="operations-grid"):
            for operation in OPERATIONS:
                with Vertical(classes="operation-card"):
                    yield Static(operation.title, classes="operation-title")
                    yield Static(operation.description, classes="muted")
                    yield Button("Run", id=f"operation-{operation.identifier}")
        yield Static("Activity", classes="section-title")
        yield RichLog(id="activity-log", markup=True, wrap=True, highlight=True)


class HelpPage(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Help and safety", classes="page-title")
        yield Static(
            "Designed for repeatable operation across different homelabs.", classes="page-subtitle"
        )
        yield Static("Keyboard", classes="section-title")
        yield Static(
            "[b]1[/b] Overview    [b]2[/b] Configuration    [b]3[/b] Operations    "
            "[b]?[/b] Help    [b]Q[/b] Quit",
            classes="notice",
        )
        yield Static("Configuration policy", classes="section-title")
        yield Static(
            "General settings contain no passwords or token secrets. The Proxmox token secret "
            "is supplied at runtime through PROXMOX_VE_API_TOKEN and will later be sourced from "
            "a SOPS-encrypted secret file.",
            classes="body-copy",
        )
        yield Static("Change safety", classes="section-title")
        yield Static(
            "Unknown configuration keys fail validation. Files are replaced atomically. Future "
            "apply and destroy operations use a confirmation dialog and will present a plan first.",
            classes="body-copy",
        )


class ControlPlaneApp(App[None]):
    TITLE = "Homelab Control Plane"
    SUB_TITLE = "Operations Console"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-compact"), (100, "-wide"), (140, "-very-wide")]
    BINDINGS: ClassVar = [
        ("q", "quit", "Quit"),
        ("1", "show_page('overview')", "Overview"),
        ("2", "show_page('configuration')", "Configuration"),
        ("3", "show_page('operations')", "Operations"),
        ("?", "show_page('help')", "Help"),
    ]

    CSS = """
    $hl-background: #08111f;
    $hl-surface: #0e1b2d;
    $hl-border: #294467;
    $hl-accent: #37b7ff;
    $hl-accent-soft: #163b5c;
    $hl-success: #4ade80;
    $hl-warning: #fbbf24;
    $hl-danger: #fb7185;
    $hl-text: #e6edf7;
    $hl-muted: #8ea5c1;

    Screen { background: $hl-background; color: $hl-text; }
    Header { background: #0b1728; color: $hl-text; }
    Footer { background: #0b1728; color: $hl-muted; }
    #app-shell { height: 1fr; }
    #sidebar {
        width: 28;
        height: 1fr;
        padding: 1;
        background: #0b1728;
        border-right: solid $hl-border;
    }
    #brand { height: 5; padding: 1; color: $hl-accent; text-style: bold; }
    #brand-subtitle { color: $hl-muted; text-style: none; }
    .nav-button { width: 1fr; margin-bottom: 1; text-align: left; }
    #config-path { dock: bottom; height: auto; color: $hl-muted; padding: 1; }
    #pages { width: 1fr; height: 1fr; }
    OverviewPage, ConfigurationPage, OperationsPage, HelpPage { padding: 2 3; }
    .page-title { height: 2; text-style: bold; color: $hl-text; }
    .page-subtitle { height: 3; color: $hl-muted; }
    .section-title { height: 2; margin-top: 1; text-style: bold; color: $hl-text; }
    #status-grid { grid-size: 3 1; grid-columns: 1fr 1fr 1fr; grid-gutter: 1; height: 9; }
    .status-card, .operation-card, .form-section {
        background: $hl-surface;
        border: solid $hl-border;
        padding: 1 2;
    }
    .eyebrow { height: 1; color: $hl-accent; text-style: bold; }
    .metric { height: 2; margin-top: 1; text-style: bold; color: $hl-success; }
    .metric-warning { color: $hl-warning; }
    .muted { color: $hl-muted; }
    .quick-actions { height: 4; }
    .quick-actions Button { margin-right: 1; }
    .notice { background: $hl-accent-soft; border-left: thick $hl-accent; padding: 1 2; height: auto; }
    .body-copy { background: $hl-surface; border: solid $hl-border; padding: 1 2; height: auto; }
    .form-section { height: auto; margin-bottom: 1; }
    .field-label { height: 1; margin-top: 1; color: $hl-muted; }
    Input, Select { margin-bottom: 1; border: tall $hl-border; }
    Input:focus, Select:focus { border: tall $hl-accent; }
    .switch-row { height: 3; align-vertical: middle; }
    .switch-row Label { width: 1fr; }
    .switch-row Switch { width: auto; }
    #config-feedback { min-height: 2; height: auto; padding: 1 2; }
    .feedback-error { color: $hl-danger; background: #321724; border-left: thick $hl-danger; }
    .feedback-success { color: $hl-success; }
    .form-actions { height: 4; align-horizontal: right; }
    .form-actions Button { margin-left: 1; }
    #operations-grid { grid-size: 3 1; grid-columns: 1fr 1fr 1fr; grid-gutter: 1; height: 11; }
    .operation-title { height: 2; text-style: bold; color: $hl-text; }
    .operation-card Button { dock: bottom; width: 1fr; }
    #activity-log { height: 1fr; min-height: 12; background: #050b13; border: solid $hl-border; padding: 1; }
    ConfirmDialog { align: center middle; background: rgba(3, 8, 16, 0.80); }
    #confirm-dialog { width: 64; height: auto; background: $hl-surface; border: thick $hl-danger; padding: 2; }
    .dialog-title { height: 2; text-style: bold; }
    .dialog-detail { height: auto; color: $hl-muted; margin-bottom: 1; }
    .dialog-actions { height: 3; align-horizontal: right; }
    .dialog-actions Button { margin-left: 1; }

    Screen.-compact #sidebar { display: none; }
    Screen.-compact OverviewPage,
    Screen.-compact ConfigurationPage,
    Screen.-compact OperationsPage,
    Screen.-compact HelpPage { padding: 1 2; }
    Screen.-wide #sidebar { width: 22; }
    Screen.-wide #config-path { display: none; }
    Screen.-very-wide #sidebar { width: 28; }
    Screen.-very-wide #config-path { display: block; }
    """

    def __init__(self, config_path: Path, *, initial_page: str = "overview") -> None:
        super().__init__()
        self.config_path = config_path
        self.initial_page = initial_page

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="app-shell"):
            with Vertical(id="sidebar"):
                yield Static("HOMELAB\n[dim]CONTROL PLANE[/dim]", id="brand")
                yield Button(
                    "1  Overview", id="nav-overview", classes="nav-button", variant="primary"
                )
                yield Button("2  Configuration", id="nav-configuration", classes="nav-button")
                yield Button("3  Operations", id="nav-operations", classes="nav-button")
                yield Button("?  Help", id="nav-help", classes="nav-button")
                yield Static(f"CONFIG\n{self.config_path}", id="config-path")
            with ContentSwitcher(initial=self.initial_page, id="pages"):
                yield OverviewPage(self.config_path, id="overview")
                yield ConfigurationPage(self.config_path, id="configuration")
                yield OperationsPage(id="operations")
                yield HelpPage(id="help")
        yield Footer()

    def on_mount(self) -> None:
        self.show_page(self.initial_page)

    def action_show_page(self, page: str) -> None:
        self.show_page(page)

    def show_page(self, page: str) -> None:
        self.query_one("#pages", ContentSwitcher).current = page
        for name in ("overview", "configuration", "operations", "help"):
            button = self.query_one(f"#nav-{name}", Button)
            button.variant = "primary" if name == page else "default"
        if page == "overview":
            self.query_one(OverviewPage).refresh_status()

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        identifier = event.button.id or ""
        if identifier.startswith("nav-"):
            self.show_page(identifier.removeprefix("nav-"))
        elif identifier == "quick-config":
            self.show_page("configuration")
        elif identifier == "quick-validate":
            self.show_page("operations")
            self.run_operation("validate")
        elif identifier == "quick-doctor":
            self.show_page("operations")
            self.run_operation("doctor")
        elif identifier.startswith("operation-"):
            self.run_operation(identifier.removeprefix("operation-"))

    @on(ConfigurationPage.Saved)
    def configuration_saved(self) -> None:
        self.query_one(OverviewPage).refresh_status()

    @work(group="operations", exclusive=True)
    async def run_operation(self, identifier: str) -> None:
        log = self.query_one("#activity-log", RichLog)
        operation = next(item for item in OPERATIONS if item.identifier == identifier)
        log.write(f"[bold cyan]▶ {operation.title}[/bold cyan]")
        result: OperationResult = await asyncio.to_thread(execute, identifier, self.config_path)
        color = "green" if result.succeeded else "red"
        for line in result.lines:
            log.write(line)
        log.write(
            f"[{color}]{'✓ Completed' if result.succeeded else '✗ Action needs attention'}[/{color}]\n"
        )
        self.notify(
            f"{result.title}: {'completed' if result.succeeded else 'needs attention'}",
            severity="information" if result.succeeded else "warning",
        )
