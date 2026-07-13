"""Command-line entry point for interactive and unattended use."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from homelabctl import __version__
from homelabctl.configuration import (
    ConfigurationError,
    find_project_root,
    initialize_config,
    load_config,
    redacted_mapping,
    resolve_config_path,
    write_schema,
)
from homelabctl.doctor import checks_succeeded, run_checks
from homelabctl.proxmox_bootstrap import (
    DEFAULT_ROLE_ID,
    ProxmoxBootstrapError,
    apply_bootstrap,
    build_plan,
)
from homelabctl.secrets import (
    SecretError,
    edit_secret_file,
    initialize_secret_file,
    load_secrets,
    resolve_secrets_path,
    write_sops_policy,
)
from homelabctl.tofu import TofuError, check_foundation
from homelabctl.updater import UpdateError, apply_update, prepare_update


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        help="site configuration path (default: HOMELAB_CONFIG or config/sites/local.yaml)",
    )


def _add_secrets_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--secrets",
        type=Path,
        help="encrypted secret path (default: HOMELAB_SECRETS or config/secrets/local.enc.yaml)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="homelabctl",
        description="Operate and configure the Homelab control plane.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command")

    menu = subcommands.add_parser("menu", help="open the interactive control panel")
    _add_config_argument(menu)
    menu.add_argument(
        "--page",
        choices=(
            "overview",
            "configuration",
            "setup",
            "proxmox",
            "infrastructure",
            "maintenance",
            "diagnostics",
            "operations",
            "help",
        ),
        default="overview",
        help="initial control-panel page (operations remains an alias for setup)",
    )

    init = subcommands.add_parser("init", help="create a site configuration from safe defaults")
    _add_config_argument(init)
    init.add_argument("--force", action="store_true", help="replace an existing configuration")

    validate = subcommands.add_parser("validate", help="validate site configuration")
    _add_config_argument(validate)

    show = subcommands.add_parser("show", help="print the effective non-secret configuration")
    _add_config_argument(show)
    show.add_argument("--json", action="store_true", help="emit JSON instead of YAML")

    doctor = subcommands.add_parser("doctor", help="check control-plane readiness")
    _add_config_argument(doctor)
    _add_secrets_argument(doctor)

    update = subcommands.add_parser(
        "update", help="safely update from the configured GitHub branch"
    )
    _add_config_argument(update)
    update.add_argument(
        "--apply", action="store_true", help="apply the displayed fast-forward update"
    )

    secrets = subcommands.add_parser("secrets", help="manage SOPS-encrypted runtime credentials")
    secret_commands = secrets.add_subparsers(dest="secrets_command", required=True)

    secrets_init = secret_commands.add_parser(
        "init", help="create an encrypted placeholder file for an age recipient"
    )
    _add_secrets_argument(secrets_init)
    secrets_init.add_argument("--age-recipient", required=True, help="public age recipient")
    secrets_init.add_argument("--force", action="store_true", help="replace an existing file")

    secrets_edit = secret_commands.add_parser("edit", help="edit credentials through SOPS")
    _add_secrets_argument(secrets_edit)

    secrets_check = secret_commands.add_parser(
        "check", help="decrypt and validate credentials without displaying them"
    )
    _add_config_argument(secrets_check)
    _add_secrets_argument(secrets_check)

    proxmox = subcommands.add_parser("proxmox", help="manage Proxmox bootstrap operations")
    proxmox_commands = proxmox.add_subparsers(dest="proxmox_command", required=True)
    proxmox_bootstrap = proxmox_commands.add_parser(
        "bootstrap", help="plan or apply the API user, role, ACL, and token bootstrap"
    )
    _add_config_argument(proxmox_bootstrap)
    _add_secrets_argument(proxmox_bootstrap)
    proxmox_bootstrap.add_argument(
        "--ssh-target", help="administrator SSH target (default: root@Proxmox-host)"
    )

    proxmox_bootstrap.add_argument(
        "--ssh-private-key", type=Path, help="dedicated administrator SSH private key"
    )
    proxmox_bootstrap.add_argument("--role", default=DEFAULT_ROLE_ID, help="custom Proxmox role ID")
    proxmox_bootstrap.add_argument(
        "--apply", action="store_true", help="apply the displayed bootstrap plan"
    )
    proxmox_bootstrap.add_argument(
        "--rotate-token",
        action="store_true",
        help="explicitly replace an existing token and update SOPS",
    )

    tofu = subcommands.add_parser("tofu", help="check the OpenTofu infrastructure foundation")
    tofu_commands = tofu.add_subparsers(dest="tofu_command", required=True)
    tofu_check = tofu_commands.add_parser(
        "check", help="initialize providers, validate inputs, and create a saved plan"
    )
    _add_config_argument(tofu_check)
    _add_secrets_argument(tofu_check)

    schema = subcommands.add_parser("schema", help="write the JSON Schema for site configuration")
    schema.add_argument("--output", type=Path, default=Path("config/schema/site.schema.json"))
    return parser


def _show_config(config_path: Path, *, as_json: bool) -> int:
    config = load_config(config_path)
    data = redacted_mapping(config)
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), end="")
    return 0


def _doctor(config_path: Path, secrets_path: Path | None, console: Console) -> int:
    results = run_checks(config_path, secrets_path)
    table = Table(title="Control-plane readiness", header_style="bold cyan")
    table.add_column("Status", width=8)
    table.add_column("Check", style="bold")
    table.add_column("Detail")
    colors = {"pass": "green", "warn": "yellow", "fail": "red"}
    for result in results:
        table.add_row(
            f"[{colors[result.status]}]{result.status.upper()}[/]", result.name, result.detail
        )
    console.print(table)
    return 0 if checks_succeeded(results) else 1


def _update(config_path: Path, *, apply: bool, console: Console) -> int:
    root = find_project_root(config_path.parent)
    plan = prepare_update(root)
    console.print("[bold cyan]Control-plane update plan[/]")
    console.print(f"- Current version: {plan.current_commit[:12]}")
    console.print(f"- GitHub version: {plan.target_commit[:12]}")
    console.print(f"- Changed files: {len(plan.changed_files)}")
    if not apply:
        console.print("[yellow]Plan only. Re-run with --apply to install the update.[/]")
        return 0
    result = apply_update(root)
    if result.updated:
        console.print(
            f"[green]Updated control plane:[/] {result.previous_commit[:12]} -> "
            f"{result.current_commit[:12]}"
        )
        console.print("Restart the menu to load the new code.")
    else:
        console.print(f"[green]Already current:[/] {result.current_commit[:12]}")
    return 0


def _secrets_init(path: Path | None, recipient: str, force: bool, console: Console) -> int:
    secret_path = initialize_secret_file(path, age_recipient=recipient, force=force)
    policy_path, created = write_sops_policy(recipient, start=secret_path.parent)
    console.print(f"[green]Created encrypted secret file:[/] {secret_path}")
    console.print(
        f"[green]Created SOPS recipient policy:[/] {policy_path}"
        if created
        else f"[yellow]Kept existing SOPS recipient policy:[/] {policy_path}"
    )
    console.print("Run `homelabctl secrets edit` to replace the encrypted placeholders.")
    return 0


def _secrets_check(config_path: Path, secrets_path: Path | None, console: Console) -> int:
    config = load_config(config_path)
    bundle = load_secrets(secrets_path, config=config)
    providers = ", ".join(bundle.provider_names())
    console.print(
        f"[green]Encrypted secrets ready:[/] {providers} | {resolve_secrets_path(secrets_path)}"
    )
    return 0


def _proxmox_bootstrap(args: argparse.Namespace, console: Console) -> int:
    config = load_config(resolve_config_path(args.config))
    plan = build_plan(
        config,
        ssh_target=args.ssh_target,
        role_id=args.role,
        rotate_token=args.rotate_token,
    )
    console.print("[bold cyan]Proxmox API identity bootstrap plan[/]")
    for line in plan.lines():
        console.print(f"- {line}")
    if not args.apply:
        console.print("[yellow]Plan only. Re-run with --apply to make these changes.[/]")
        return 0
    result = apply_bootstrap(
        config,
        args.secrets,
        ssh_target=args.ssh_target,
        role_id=args.role,
        rotate_token=args.rotate_token,
        ssh_private_key=args.ssh_private_key,
    )
    action = "created or rotated" if result.created_or_rotated else "reconciled"
    console.print(
        f"[green]Proxmox API identity {action} and verified:[/] "
        f"{result.token_id} | role {result.role_id}"
    )
    return 0


def _tofu_check(args: argparse.Namespace, console: Console) -> int:
    result = check_foundation(resolve_config_path(args.config), args.secrets)
    console.print("[green]OpenTofu foundation checks passed[/]")
    console.print(f"[green]Non-destructive plan:[/] {result.plan_path}")
    console.print(f"[cyan]Diagnostic log:[/] {result.diagnostic_log}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "menu"
    console = Console()

    try:
        if command == "menu":
            from homelabctl.ui import ControlPlaneApp

            ControlPlaneApp(
                resolve_config_path(getattr(args, "config", None)),
                initial_page=getattr(args, "page", "overview"),
            ).run()
            return 0
        if command == "init":
            path = initialize_config(args.config, force=args.force)
            console.print(f"[green]Created configuration:[/] {path}")
            return 0
        if command == "validate":
            path = resolve_config_path(args.config)
            config = load_config(path)
            console.print(
                f"[green]Valid configuration[/] | {config.site.name} | "
                f"{config.site.environment} | {path}"
            )
            return 0
        if command == "show":
            return _show_config(resolve_config_path(args.config), as_json=args.json)
        if command == "doctor":
            return _doctor(resolve_config_path(args.config), args.secrets, console)
        if command == "update":
            return _update(resolve_config_path(args.config), apply=args.apply, console=console)
        if command == "secrets":
            if args.secrets_command == "init":
                return _secrets_init(args.secrets, args.age_recipient, args.force, console)
            if args.secrets_command == "edit":
                path = edit_secret_file(args.secrets)
                console.print(f"[green]Saved encrypted secret file:[/] {path}")
                return 0
            if args.secrets_command == "check":
                return _secrets_check(resolve_config_path(args.config), args.secrets, console)
        if command == "proxmox" and args.proxmox_command == "bootstrap":
            return _proxmox_bootstrap(args, console)
        if command == "tofu" and args.tofu_command == "check":
            return _tofu_check(args, console)
        if command == "schema":
            path = write_schema(args.output)
            console.print(f"[green]Wrote schema:[/] {path}")
            return 0
    except (ConfigurationError, ProxmoxBootstrapError, SecretError, TofuError, UpdateError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    parser.error(f"Unknown command: {command}")
    return 2
