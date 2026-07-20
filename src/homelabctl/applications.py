"""Curated, immutable in-guest application adapters."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from homelabctl.ansible import AnsibleError, _run_ansible_with_live_output, generate_inventory
from homelabctl.configuration import find_project_root, load_config
from homelabctl.guard import OperationLockedError, mutation_lock
from homelabctl.progress import is_enabled as live_progress_enabled
from homelabctl.secrets import load_secrets

UPTIME_KUMA_VERSION = "2.4.0"
UPTIME_KUMA_SOURCE_SHA256 = "0ad39c4cbe2de5a2dd4869d02a8a4f0398b7b16217b0aeaff98d78cf37500c42"
UPTIME_KUMA_DIST_SHA256 = "015ebb4df74b72bd8c303bdc41b71e2de8bdc72862ddc2d65db69a92316df835"
COMMUNITY_SCRIPTS_REVISION = "b9f26d66ed5131bcded155ebb83784f303cf4355"
TECHNITIUM_VERSION = "15.4.0"
TECHNITIUM_SHA256 = "461ac09d4304ace85093fc17b10a7ee13a8796eae0adb4393866bd4d66ab283f"
DOTNET_RUNTIME_VERSION = "10.0.10"
DOTNET_RUNTIME_SHA512 = (
    "4719249fcaca744b8edfa5b653366cabdd25f452a7cb9e961b8671ddd2f80ecee"
    "f4bb8b74e0fad899f93e5c7c8b138890ff0bdb49f2daecb489455d9487a572b"
)


class ApplicationError(RuntimeError):
    """Raised when a curated application operation is unsafe or fails."""


@dataclass(frozen=True, slots=True)
class ApplicationResult:
    application: str
    guest: str
    diagnostic_log: Path
    lines: tuple[str, ...]


def application_plan(config_path: Path) -> tuple[str, ...]:
    config = load_config(config_path)
    enabled = [(key, app) for key, app in config.applications.items() if app.enabled]
    if not enabled:
        raise ApplicationError("No enabled curated applications are configured")
    lines: list[str] = []
    if any(app.type == "uptime-kuma" for _, app in enabled):
        lines.extend(
            [
                f"Community Scripts reviewed revision: {COMMUNITY_SCRIPTS_REVISION}",
                f"Uptime Kuma version: {UPTIME_KUMA_VERSION}",
                f"Source SHA-256: {UPTIME_KUMA_SOURCE_SHA256}",
                f"Frontend SHA-256: {UPTIME_KUMA_DIST_SHA256}",
            ]
        )
    if any(app.type == "technitium" for _, app in enabled):
        lines.extend(
            [
                f"Technitium DNS version: {TECHNITIUM_VERSION}",
                f"Technitium archive SHA-256: {TECHNITIUM_SHA256}",
                f"ASP.NET Core runtime: {DOTNET_RUNTIME_VERSION}",
                f"ASP.NET Core archive SHA-512: {DOTNET_RUNTIME_SHA512}",
            ]
        )
    lines.extend(f"{key}: {app.type} on guest {app.guest}, port {app.port}" for key, app in enabled)
    return tuple(lines)


def run_applications(config_path: Path, *, check: bool) -> ApplicationResult:
    config = load_config(config_path)
    enabled = [(key, app) for key, app in config.applications.items() if app.enabled]
    if len(enabled) != 1:
        raise ApplicationError("The pilot supports exactly one enabled curated application")
    key, application = enabled[0]
    root = find_project_root(config_path.parent)
    inventory_path, _ = generate_inventory(config_path)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    hosts = inventory["all"]["hosts"]
    if application.guest not in hosts:
        raise ApplicationError(
            f"Application guest is absent from runtime inventory: {application.guest}"
        )
    hosts[application.guest]["ansible_user"] = config.automation.ssh_user
    hosts[application.guest]["ansible_become"] = config.automation.become
    inventory["all"]["hosts"] = {application.guest: hosts[application.guest]}
    app_inventory = root / ".cache" / "ansible" / "applications.json"
    app_inventory.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    ansible = shutil.which("ansible-playbook")
    if not ansible:
        raise ApplicationError("ansible-playbook is not installed or not on PATH")
    playbook = {
        "uptime-kuma": "uptime-kuma.yml",
        "technitium": "technitium.yml",
    }[application.type]
    extra_vars = (
        {"uptime_kuma_port": application.port}
        if application.type == "uptime-kuma"
        else {"technitium_web_port": application.port}
    )
    environment_updates: dict[str, str] = {}
    if application.type == "technitium":
        bundle = load_secrets(config=config)
        credential = application.credential or ""
        if credential not in bundle.credentials:
            raise ApplicationError(
                f"Encrypted secrets are missing required credential: {credential}"
            )
        environment_updates["HOMELAB_TECHNITIUM_ADMIN_PASSWORD"] = bundle.credentials[
            credential
        ].value.get_secret_value()
    command = [
        ansible,
        "-i",
        str(app_inventory),
        str(root / "ansible" / "applications" / playbook),
        "--extra-vars",
        json.dumps(extra_vars),
        "--diff",
    ]
    if check:
        command.append("--check")
    diagnostic = root / "logs" / "applications.log"
    try:
        if live_progress_enabled():
            if check:
                completed = _run_ansible_with_live_output(
                    command,
                    root,
                    diagnostic,
                    timeout_seconds=900,
                    environment_updates=environment_updates,
                )
            else:
                with mutation_lock(root, f"Application apply: {key}"):
                    completed = _run_ansible_with_live_output(
                        command,
                        root,
                        diagnostic,
                        timeout_seconds=900,
                        environment_updates=environment_updates,
                    )
        elif check:
            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, **environment_updates},
            )
        else:
            with mutation_lock(root, f"Application apply: {key}"):
                completed = subprocess.run(
                    command,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env={**os.environ, **environment_updates},
                )
    except (OSError, subprocess.SubprocessError, OperationLockedError, AnsibleError) as exc:
        raise ApplicationError(str(exc)) from exc
    if not live_progress_enabled():
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        output = "\n".join((completed.stdout, completed.stderr)).strip()
        diagnostic.write_text(output + "\n", encoding="utf-8")
    if completed.returncode != 0:
        raise ApplicationError(f"Application operation failed; review {diagnostic}")
    recap = tuple(
        line for line in completed.stdout.splitlines() if line.startswith(application.guest)
    )
    return ApplicationResult(
        key, application.guest, diagnostic, recap or application_plan(config_path)
    )
