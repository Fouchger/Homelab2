"""Safe operations exposed by the control-panel menu."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from homelabctl.configuration import (
    ConfigurationError,
    load_config,
    redacted_mapping,
    resolve_config_path,
)
from homelabctl.doctor import checks_succeeded, run_checks


@dataclass(frozen=True, slots=True)
class OperationResult:
    succeeded: bool
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Operation:
    identifier: str
    title: str
    description: str
    run: Callable[[Path], OperationResult]
    destructive: bool = False


def validate_configuration(path: Path) -> OperationResult:
    try:
        config = load_config(path)
    except ConfigurationError as exc:
        return OperationResult(False, "Configuration validation", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Configuration validation",
        (
            f"Validated {path}",
            f"Site: {config.site.name}",
            f"Environment: {config.site.environment}",
            f"Proxmox node: {config.proxmox.node}",
            f"Management network: {config.network.management_cidr}",
        ),
    )


def system_readiness(path: Path) -> OperationResult:
    checks = run_checks(path)
    symbols = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = tuple(f"[{symbols[result.status]}] {result.name}: {result.detail}" for result in checks)
    return OperationResult(checks_succeeded(checks), "System readiness", lines)


def configuration_summary(path: Path) -> OperationResult:
    try:
        config = load_config(path)
    except ConfigurationError as exc:
        return OperationResult(False, "Configuration summary", tuple(str(exc).splitlines()))
    rendered = yaml.safe_dump(
        redacted_mapping(config), sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return OperationResult(True, "Configuration summary", tuple(rendered.rstrip().splitlines()))


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "validate",
        "Validate configuration",
        "Check every site value and reject unknown or unsafe settings.",
        validate_configuration,
    ),
    Operation(
        "doctor",
        "Check system readiness",
        "Inspect the local toolchain, configuration, and provisioning credential.",
        system_readiness,
    ),
    Operation(
        "summary",
        "Preview effective settings",
        "Display the exact non-secret values automation will consume.",
        configuration_summary,
    ),
)


def get_operation(identifier: str) -> Operation:
    for operation in OPERATIONS:
        if operation.identifier == identifier:
            return operation
    raise KeyError(f"Unknown operation: {identifier}")


def execute(identifier: str, path: str | Path | None = None) -> OperationResult:
    operation = get_operation(identifier)
    return operation.run(resolve_config_path(path))
