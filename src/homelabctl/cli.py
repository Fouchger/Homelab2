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
    initialize_config,
    load_config,
    redacted_mapping,
    resolve_config_path,
    write_schema,
)
from homelabctl.doctor import checks_succeeded, run_checks


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        help="site configuration path (default: HOMELAB_CONFIG or config/sites/local.yaml)",
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
        choices=("overview", "configuration", "operations", "help"),
        default="overview",
        help="initial control-panel page",
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


def _doctor(config_path: Path, console: Console) -> int:
    results = run_checks(config_path)
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
            return _doctor(resolve_config_path(args.config), console)
        if command == "schema":
            path = write_schema(args.output)
            console.print(f"[green]Wrote schema:[/] {path}")
            return 0
    except ConfigurationError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    parser.error(f"Unknown command: {command}")
    return 2
