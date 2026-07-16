"""Professional terminal control panel built with Textual."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar, TypeVar

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
    TextArea,
)

from homelabctl.configuration import ConfigurationError, find_project_root, load_config, save_config
from homelabctl.doctor import run_checks
from homelabctl.models import HomelabConfig, default_config
from homelabctl.operations import OPERATIONS, OperationResult, execute, execute_with_secret

T = TypeVar("T")


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


class SecretInputDialog(ModalScreen[str | None]):
    """Collect one credential without displaying or logging it."""

    def __init__(self, title: str, detail: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="secret-input-dialog"):
            yield Static(self.dialog_title, classes="dialog-title")
            yield Static(self.detail, classes="dialog-detail")
            yield Label("API token", classes="field-label")
            yield Input(password=True, id="secret-input-value")
            with Horizontal(classes="dialog-actions"):
                yield Button("Cancel", id="secret-input-cancel")
                yield Button("Encrypt and save", id="secret-input-save", variant="success")

    @on(Button.Pressed, "#secret-input-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#secret-input-save")
    def save(self) -> None:
        value = self.query_one("#secret-input-value", Input).value.strip()
        if not value:
            self.app.notify("Enter the API token", severity="warning")
            return
        self.dismiss(value)


class CopyCommandDialog(ModalScreen[bool]):
    """Show a command separately, copy it, or run it interactively outside the TUI."""

    def __init__(
        self,
        command: str,
        interactive_command: tuple[str, ...],
        fallback_command: str | None = None,
    ) -> None:
        super().__init__()
        self.command = command
        self.interactive_command = interactive_command
        self.fallback_command = fallback_command

    def compose(self) -> ComposeResult:
        with Vertical(id="copy-command-dialog"):
            yield Static("Authorize the Proxmox SSH key", classes="dialog-title")
            yield Static(
                "Recommended: install the public key automatically. The menu will temporarily "
                "close so ssh-copy-id can request the Proxmox root password; the password is "
                "handled by SSH and is never stored.",
                classes="dialog-detail",
            )
            yield Label("Command run on the control plane", classes="field-label")
            yield TextArea(
                self.command,
                read_only=True,
                show_cursor=True,
                soft_wrap=True,
                id="copy-command-text",
            )
            with Horizontal(classes="dialog-actions"):
                yield Button("Install key automatically", id="command-run", variant="success")
                yield Button("Copy command", id="command-copy")
                yield Button("Close", id="command-close")
            if self.fallback_command is not None:
                yield Static(
                    "If root password SSH is disabled, copy this fallback and run it once in the "
                    "Proxmox web shell or physical console.",
                    classes="dialog-detail",
                )
                yield TextArea(
                    self.fallback_command,
                    read_only=True,
                    show_cursor=True,
                    soft_wrap=True,
                    id="fallback-command-text",
                )
                yield Button("Copy console fallback", id="fallback-copy")

    @on(Button.Pressed, "#command-copy")
    def copy_command(self) -> None:
        self.app.copy_to_clipboard(self.command)
        self.app.notify("ssh-copy-id command copied", severity="information")

    @on(Button.Pressed, "#fallback-copy")
    def copy_fallback(self) -> None:
        if self.fallback_command is not None:
            self.app.copy_to_clipboard(self.fallback_command)
            self.app.notify("Proxmox console command copied", severity="information")

    @on(Button.Pressed, "#command-run")
    def run_command(self) -> None:
        try:
            with self.app.suspend():
                completed = subprocess.run(list(self.interactive_command), check=False)
        except OSError:
            self.app.notify("ssh-copy-id could not be started", severity="error")
            return
        if completed.returncode == 0:
            self.app.notify("Proxmox SSH key authorized", severity="information")
            self.dismiss(True)
        else:
            self.app.notify(
                "Automatic key installation failed; use the console fallback",
                severity="warning",
            )

    @on(Button.Pressed, "#command-close")
    def close_dialog(self) -> None:
        self.dismiss(False)


class ActivityCopyDialog(ModalScreen[None]):
    """Offer portable activity-copy methods for local and remote terminals."""

    def __init__(self, transcript: str, report_path: Path) -> None:
        super().__init__()
        self.transcript = transcript
        self.report_path = report_path

    def compose(self) -> ComposeResult:
        with Vertical(id="activity-copy-dialog"):
            yield Static("Copy session activity", classes="dialog-title")
            yield Static(
                "Remote terminals may block direct clipboard access. Recommended: open the "
                "plain terminal view, select and copy with MobaXterm or the browser, then press "
                "Enter to return to this menu.",
                classes="dialog-detail",
            )
            yield Label(
                "Plain-text activity (secret values are never included)", classes="field-label"
            )
            yield TextArea(
                self.transcript,
                read_only=True,
                show_cursor=True,
                soft_wrap=True,
                id="activity-copy-text",
            )
            yield Static(f"Saved fallback: {self.report_path}", classes="dialog-detail")
            with Horizontal(classes="dialog-actions"):
                yield Button(
                    "Open terminal copy view", id="activity-copy-terminal", variant="success"
                )
                yield Button("Try direct clipboard", id="activity-copy-direct")
                yield Button("Close", id="activity-copy-close")

    def on_mount(self) -> None:
        text_area = self.query_one("#activity-copy-text", TextArea)
        text_area.focus()
        text_area.select_all()

    @on(Button.Pressed, "#activity-copy-terminal")
    def open_terminal_copy_view(self) -> None:
        with self.app.suspend():
            print("\n--- Homelab Control Plane activity ---\n")
            print(self.transcript, end="")
            print("\n--- End activity ---")
            input("Select and copy the text above, then press Enter to return to the menu...")
        text_area = self.query_one("#activity-copy-text", TextArea)
        text_area.focus()
        text_area.select_all()

    @on(Button.Pressed, "#activity-copy-direct")
    def try_direct_clipboard(self) -> None:
        self.app.copy_to_clipboard(self.transcript)
        self.app.notify(
            "Clipboard request sent; use the terminal view if your client blocks it",
            severity="information",
        )

    @on(Button.Pressed, "#activity-copy-close")
    def close_dialog(self) -> None:
        self.dismiss(None)


class OverviewPage(VerticalScroll):
    def __init__(self, config_path: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.config_path = config_path
        self.loaded_config: HomelabConfig | None = None

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
            "Encrypted-secret setup and the guarded Proxmox API identity bootstrap are available "
            "in their dedicated menu sections. OpenTofu checks are under Infrastructure.",
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
            "Values are validated before an atomic save. YAML-managed guests and DNS records are preserved.",
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
            yield Static("External DNS", classes="section-title")
            for widget in self.field(
                "Cloudflare domains (comma separated, optional)",
                "field-cloudflare-domains",
                "example.com, example.net",
            ):
                yield widget
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
        self.loaded_config = config

        values = {
            "#field-site-name": config.site.name,
            "#field-domain": config.site.domain,
            "#field-cloudflare-domains": ", ".join(config.cloudflare.domains),
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
        source = self.loaded_config or default_config()
        data = source.model_dump(mode="json")
        data["site"].update(
            {
                "name": value("#field-site-name"),
                "domain": value("#field-domain"),
                "timezone": value("#field-timezone"),
                "environment": self.query_one("#field-environment", Select).value,
            }
        )
        data["cloudflare"].update(
            {
                "domains": [
                    item.strip()
                    for item in value("#field-cloudflare-domains").split(",")
                    if item.strip()
                ],
            }
        )
        data["proxmox"].update(
            {
                "api_url": value("#field-api-url"),
                "node": value("#field-node"),
                "storage": value("#field-storage"),
                "token_id": value("#field-token-id"),
                "verify_tls": self.query_one("#field-verify-tls", Switch).value,
            }
        )
        data["network"].update(
            {
                "management_cidr": value("#field-cidr"),
                "gateway": value("#field-gateway"),
                "dns_servers": [
                    item.strip() for item in value("#field-dns").split(",") if item.strip()
                ],
                "bridge": value("#field-bridge"),
                "vlan_id": int(vlan) if vlan else None,
            }
        )
        data["automation"].update(
            {
                "ssh_user": value("#field-ssh-user"),
                "ssh_private_key": value("#field-ssh-key"),
                "become": self.query_one("#field-become", Switch).value,
            }
        )
        data["deployment"].update(
            {
                "channel": self.query_one("#field-channel", Select).value,
                "check_interval_minutes": value("#field-interval"),
                "automatic_updates": self.query_one("#field-auto-updates", Switch).value,
                "require_confirmation": self.query_one("#field-confirmation", Switch).value,
            }
        )
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
        self.loaded_config = config
        self.set_feedback(f"Saved and validated {saved_path}", error=False)
        self.app.notify("Configuration saved", severity="information")
        self.post_message(self.Saved(config))


ACTION_SECTIONS: dict[str, tuple[str, str]] = {
    "setup": (
        "Setup",
        "Prepare and validate the control plane, configuration, and encrypted credentials.",
    ),
    "proxmox": (
        "Proxmox",
        "Establish administrator access and reconcile the least-privilege API identity.",
    ),
    "infrastructure": (
        "Infrastructure",
        "Validate infrastructure definitions and preview changes before deployment.",
    ),
    "maintenance": (
        "Maintenance",
        "Keep the control-plane software current through guarded, non-destructive updates.",
    ),
    "diagnostics": (
        "Diagnostics",
        "Inspect readiness, review effective settings, and copy session activity for support.",
    ),
}


SECTION_GUIDANCE: dict[str, str] = {
    "setup": "Follow the steps in order. The Cloudflare token step is needed only when external domains are configured.",
    "proxmox": "Prepare administrator SSH access before bootstrapping the API identity.",
    "infrastructure": "Follow the steps in order: guest key, OpenTofu, inventory, baseline, then applications.",
    "maintenance": "Review the update plan before applying it.",
    "diagnostics": "Run readiness first, then inspect the effective non-secret settings if needed.",
}


class ActionPage(VerticalScroll):
    def __init__(self, section: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.section = section

    def compose(self) -> ComposeResult:
        title, subtitle = ACTION_SECTIONS[self.section]
        operations = sorted(
            (
                operation
                for operation in OPERATIONS
                if operation.visible and operation.section == self.section
            ),
            key=lambda operation: (operation.sequence, operation.identifier),
        )
        yield Static(title, classes="page-title")
        yield Static(subtitle, classes="page-subtitle")
        yield Static(SECTION_GUIDANCE[self.section], classes="section-guidance")
        if len(operations) > 3:
            yield Static(
                f"{len(operations)} available actions · scroll to view every action",
                classes="actions-hint",
            )
        with Grid(classes=f"actions-grid action-count-{len(operations)}"):
            for step, operation in enumerate(operations, start=1):
                with Vertical(classes="operation-card"):
                    yield Static(f"STEP {step} OF {len(operations)}", classes="operation-step")
                    yield Static(operation.title, classes="operation-title")
                    yield Static(operation.description, classes="muted")
                    yield Button("Run", id=f"operation-{operation.identifier}")
        yield Static("", classes="operation-progress")
        with Horizontal(classes="activity-heading"):
            yield Static("Session activity", classes="section-title")
            yield Button("View / copy activity", id=f"copy-activity-{self.section}")
        yield RichLog(
            id=f"activity-log-{self.section}",
            classes="activity-log",
            markup=True,
            wrap=True,
            highlight=True,
        )


class HelpPage(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("Help and safety", classes="page-title")
        yield Static(
            "Designed for repeatable operation across different homelabs.", classes="page-subtitle"
        )
        yield Static("Keyboard", classes="section-title")
        yield Static(
            "[b]1[/b] Overview   [b]2[/b] Configuration   [b]3[/b] Setup   "
            "[b]4[/b] Proxmox   [b]5[/b] Infrastructure   [b]6[/b] Maintenance   "
            "[b]7[/b] Diagnostics   [b]?[/b] Help   [b]Q[/b] Quit",
            classes="notice",
        )
        yield Static("Configuration policy", classes="section-title")
        yield Static(
            "General settings contain no passwords or token secrets. Proxmox and Cloudflare "
            "tokens are decrypted from the SOPS/age secret file only when an automation "
            "operation needs them.",
            classes="body-copy",
        )
        yield Static("Change safety", classes="section-title")
        yield Static(
            "Unknown configuration keys fail validation. Files are replaced atomically. Actions "
            "that change local security state or Proxmox always present a plan and confirmation.",
            classes="body-copy",
        )
        yield Static("Activity and support", classes="section-title")
        yield Static(
            "Action results are retained across Setup, Proxmox, Infrastructure, Maintenance, "
            "and Diagnostics for this session. Select View / copy activity, or press C, to open "
            "a portable plain-text copy view without colour markup or secret values.",
            classes="body-copy",
        )


class ControlPlaneApp(App[None]):
    TITLE = "Homelab Control Plane"
    SUB_TITLE = "Management Console"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-compact"), (100, "-wide"), (140, "-very-wide")]
    BINDINGS: ClassVar = [
        ("q", "quit", "Quit"),
        ("1", "show_page('overview')", "Overview"),
        ("2", "show_page('configuration')", "Configuration"),
        ("3", "show_page('setup')", "Setup"),
        ("4", "show_page('proxmox')", "Proxmox"),
        ("5", "show_page('infrastructure')", "Infrastructure"),
        ("6", "show_page('maintenance')", "Maintenance"),
        ("7", "show_page('diagnostics')", "Diagnostics"),
        ("c", "copy_activity", "Copy activity"),
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
    OverviewPage, ConfigurationPage, ActionPage, HelpPage { padding: 2 3; }
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
    .actions-grid {
        grid-size: 3;
        grid-columns: 1fr 1fr 1fr;
        grid-rows: 9;
        grid-gutter: 1;
        height: auto;
    }
    .section-guidance { height: auto; margin-bottom: 1; color: $hl-muted; }
    .actions-hint { height: 2; color: $hl-accent; }
    .operation-step { height: 1; color: $hl-accent; text-style: bold; }
    .operation-title { height: 2; text-style: bold; color: $hl-text; }
    .operation-card Button { dock: bottom; width: 1fr; }
    .activity-heading { height: 4; margin-top: 1; align-vertical: middle; }
    .operation-progress {
        display: none;
        height: 3;
        margin-top: 1;
        padding: 1 2;
        background: #10283d;
        border-left: thick $hl-accent;
        color: $text;
    }
    .activity-heading .section-title { width: 1fr; margin-top: 0; }
    .activity-heading Button { width: 20; }
    .activity-log { height: 16; min-height: 9; background: #050b13; border: solid $hl-border; padding: 1; }
    ConfirmDialog { align: center middle; background: rgba(3, 8, 16, 0.80); }
    SecretInputDialog { align: center middle; background: rgba(3, 8, 16, 0.80); }
    CopyCommandDialog { align: center middle; background: rgba(3, 8, 16, 0.80); }
    ActivityCopyDialog { align: center middle; background: rgba(3, 8, 16, 0.80); }
    #confirm-dialog { width: 64; height: auto; background: $hl-surface; border: thick $hl-danger; padding: 2; }
    #secret-input-dialog { width: 72; height: auto; background: $hl-surface; border: thick $hl-accent; padding: 2; }
    .dialog-title { height: 2; text-style: bold; }
    .dialog-detail { height: auto; color: $hl-muted; margin-bottom: 1; }
    .dialog-actions { height: 3; align-horizontal: right; }
    .dialog-actions Button { margin-left: 1; }
    #copy-command-dialog {
        width: 92;
        height: auto;
        max-height: 34;
        background: $hl-surface;
        border: thick $hl-accent;
        padding: 2;
    }
    #copy-command-text { height: 5; border: solid $hl-border; }
    #fallback-command-text { height: 7; border: solid $hl-border; }
    #fallback-copy { width: 1fr; margin-top: 1; }
    #activity-copy-dialog {
        width: 100;
        height: 34;
        max-height: 90%;
        background: $hl-surface;
        border: thick $hl-accent;
        padding: 2;
    }
    #activity-copy-text { height: 15; border: solid $hl-border; }

    Screen.-compact #sidebar { display: none; }
    Screen.-compact OverviewPage,
    Screen.-compact ConfigurationPage,
    Screen.-compact ActionPage,
    Screen.-compact HelpPage { padding: 1 2; }
    Screen.-compact .actions-grid { grid-size: 1; grid-columns: 1fr; }
    Screen.-wide #sidebar { width: 22; }
    Screen.-wide #config-path { display: none; }
    Screen.-wide .actions-grid { grid-size: 2; grid-columns: 1fr 1fr; }
    Screen.-very-wide #sidebar { width: 28; }
    Screen.-very-wide #config-path { display: block; }
    Screen.-very-wide .actions-grid { grid-size: 3; grid-columns: 1fr 1fr 1fr; }
    """

    def __init__(self, config_path: Path, *, initial_page: str = "overview") -> None:
        super().__init__()
        self.config_path = config_path
        self.initial_page = "setup" if initial_page == "operations" else initial_page
        self._activity_lines: list[str] = []
        self._operation_active = False
        self._clock: Callable[[], float] = time.monotonic

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="app-shell"):
            with Vertical(id="sidebar"):
                yield Static("HOMELAB\n[dim]CONTROL PLANE[/dim]", id="brand")
                yield Button(
                    "1  Overview", id="nav-overview", classes="nav-button", variant="primary"
                )
                yield Button("2  Configuration", id="nav-configuration", classes="nav-button")
                yield Button("3  Setup", id="nav-setup", classes="nav-button")
                yield Button("4  Proxmox", id="nav-proxmox", classes="nav-button")
                yield Button("5  Infrastructure", id="nav-infrastructure", classes="nav-button")
                yield Button("6  Maintenance", id="nav-maintenance", classes="nav-button")
                yield Button("7  Diagnostics", id="nav-diagnostics", classes="nav-button")
                yield Button("?  Help", id="nav-help", classes="nav-button")
                yield Static(f"CONFIG\n{self.config_path}", id="config-path")
            with ContentSwitcher(initial=self.initial_page, id="pages"):
                yield OverviewPage(self.config_path, id="overview")
                yield ConfigurationPage(self.config_path, id="configuration")
                for section in ACTION_SECTIONS:
                    yield ActionPage(section, id=section)
                yield HelpPage(id="help")
        yield Footer()

    def on_mount(self) -> None:
        self.show_page(self.initial_page)

    def action_show_page(self, page: str) -> None:
        self.show_page(page)

    def show_page(self, page: str) -> None:
        self.query_one("#pages", ContentSwitcher).current = page
        for name in ("overview", "configuration", *ACTION_SECTIONS, "help"):
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
            self.show_page("setup")
            self.run_operation("validate")
        elif identifier == "quick-doctor":
            self.show_page("diagnostics")
            self.run_operation("doctor")
        elif identifier.startswith("copy-activity-"):
            self.action_copy_activity()
        elif identifier.startswith("operation-"):
            self.run_operation(identifier.removeprefix("operation-"))

    @on(ConfigurationPage.Saved)
    def configuration_saved(self) -> None:
        self.query_one(OverviewPage).refresh_status()

    def action_copy_activity(self) -> None:
        if not self._activity_lines:
            self.notify("There is no session activity to copy yet", severity="warning")
            return
        transcript = "\n".join(self._activity_lines).rstrip() + "\n"
        report_path = find_project_root(self.config_path.parent) / "logs" / "activity-report.txt"
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(transcript, encoding="utf-8", newline="\n")
            if os.name != "nt":
                report_path.chmod(0o600)
        except OSError:
            self.notify("Activity report could not be saved", severity="warning")
        self.push_screen(ActivityCopyDialog(transcript, report_path))

    def write_activity(self, rendered: str, *, plain: str | None = None) -> None:
        """Write a safe line to every activity view and the plain-text clipboard history."""

        for log in self.query(".activity-log").results(RichLog):
            log.write(rendered)
        self._activity_lines.append(rendered if plain is None else plain)

    def _set_operation_progress(self, message: str | None) -> None:
        for status in self.query(".operation-progress").results(Static):
            status.display = message is not None
            status.update(message or "")

    def _set_operation_buttons_disabled(self, disabled: bool) -> None:
        for button in self.query(".operation-card Button").results(Button):
            button.disabled = disabled

    async def _run_with_progress(self, label: str, function: Callable[..., T], *args: Any) -> T:
        started = self._clock()
        self._set_operation_progress(f"⏳ {label} · starting")
        self.write_activity(f"{label} · started")

        async def heartbeat() -> None:
            last_report = 0
            while True:
                await asyncio.sleep(1)
                elapsed = int(self._clock() - started)
                self._set_operation_progress(f"⏳ {label} · running for {elapsed}s")
                if elapsed >= last_report + 15:
                    self.write_activity(f"{label} · still running ({elapsed}s)")
                    last_report = elapsed

        progress = asyncio.create_task(heartbeat())
        try:
            result = await asyncio.to_thread(function, *args)
        finally:
            progress.cancel()
            with suppress(asyncio.CancelledError):
                await progress
        elapsed = int(self._clock() - started)
        self._set_operation_progress(f"✓ {label} · finished in {elapsed}s")
        self.write_activity(f"{label} · finished in {elapsed}s")
        return result

    @work(group="operations")
    async def run_operation(self, identifier: str) -> None:
        if self._operation_active:
            self.notify("Another operation is already running", severity="warning")
            return
        self._operation_active = True
        self._set_operation_buttons_disabled(True)
        try:
            await self._execute_operation(identifier)
        finally:
            self._operation_active = False
            self._set_operation_buttons_disabled(False)
            self._set_operation_progress(None)

    async def _execute_operation(self, identifier: str) -> None:
        operation = next(item for item in OPERATIONS if item.identifier == identifier)
        self.write_activity(
            f"[bold cyan]> {operation.title}[/bold cyan]", plain=f"> {operation.title}"
        )
        if operation.destructive:
            preview = (
                await self._run_with_progress(
                    f"Preparing {operation.title}", operation.plan, self.config_path
                )
                if operation.plan is not None
                else OperationResult(True, f"{operation.title} plan", (operation.description,))
            )
            self.write_activity("[bold yellow]Plan[/bold yellow]", plain="Plan")
            for line in preview.lines:
                self.write_activity(line)
            if not preview.succeeded:
                self.write_activity(
                    "[red]Plan needs attention; no changes were made.[/red]",
                    plain="Plan needs attention; no changes were made.",
                )
                self.write_activity("")
                self.notify(f"{preview.title}: needs attention", severity="warning")
                return
            confirmed = await self.push_screen_wait(
                ConfirmDialog(f"Confirm: {operation.title}", "\n".join(preview.lines))
            )
            if not confirmed:
                self.write_activity(
                    "[yellow]Cancelled; no changes were made.[/yellow]",
                    plain="Cancelled; no changes were made.",
                )
                self.write_activity("")
                return
        if operation.secret_prompt is not None:
            secret = await self.push_screen_wait(
                SecretInputDialog(operation.title, operation.secret_prompt)
            )
            if secret is None:
                self.write_activity(
                    "[yellow]Cancelled; the encrypted credentials were unchanged.[/yellow]",
                    plain="Cancelled; the encrypted credentials were unchanged.",
                )
                self.write_activity("")
                return
            result = await self._run_with_progress(
                operation.title, execute_with_secret, identifier, secret, self.config_path
            )
        else:
            result = await self._run_with_progress(
                operation.title, execute, identifier, self.config_path
            )
        for line in result.lines:
            self.write_activity(line)
        if (
            not result.succeeded
            and result.recovery_operation is not None
            and result.recovery_prompt is not None
        ):
            confirmed = await self.push_screen_wait(
                ConfirmDialog("Recover unavailable Proxmox token?", result.recovery_prompt)
            )
            if confirmed:
                self.write_activity(
                    "[bold yellow]Explicit token recovery confirmed[/bold yellow]",
                    plain="Explicit token recovery confirmed",
                )
                result = await self._run_with_progress(
                    "Recovering Proxmox API token",
                    execute,
                    result.recovery_operation,
                    self.config_path,
                )
                for line in result.lines:
                    self.write_activity(line)
            else:
                self.write_activity(
                    "[yellow]Token recovery cancelled; the existing token was retained.[/yellow]",
                    plain="Token recovery cancelled; the existing token was retained.",
                )
        if result.copy_text is not None and result.interactive_command is not None:
            installed = await self.push_screen_wait(
                CopyCommandDialog(
                    result.copy_text,
                    result.interactive_command,
                    result.fallback_text,
                )
            )
            message = (
                "SSH public key installed." if installed else "SSH key installation dialog closed."
            )
            self.write_activity(
                f"[{'green' if installed else 'yellow'}]{message}[/]", plain=message
            )
        color = "green" if result.succeeded else "red"
        final_message = "Completed" if result.succeeded else "Action needs attention"
        self.write_activity(f"[{color}]{final_message}[/{color}]", plain=final_message)
        self.write_activity("")
        self.notify(
            f"{result.title}: {'completed' if result.succeeded else 'needs attention'}",
            severity="information" if result.succeeded else "warning",
        )
