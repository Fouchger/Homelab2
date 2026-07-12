"""Safe operations exposed by the control-panel menu."""

from __future__ import annotations

import shlex
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
from homelabctl.proxmox_bootstrap import (
    ProxmoxBootstrapError,
    ProxmoxTokenRecoveryRequired,
    apply_bootstrap,
    build_plan,
    ensure_bootstrap_ssh_key,
    resolve_bootstrap_ssh_key,
)
from homelabctl.secrets import (
    SecretError,
    ensure_secret_store,
    resolve_age_identity_path,
    resolve_secrets_path,
)


@dataclass(frozen=True, slots=True)
class OperationResult:
    succeeded: bool
    title: str
    lines: tuple[str, ...]
    copy_text: str | None = None
    interactive_command: tuple[str, ...] | None = None
    fallback_text: str | None = None
    recovery_operation: str | None = None
    recovery_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class Operation:
    identifier: str
    title: str
    description: str
    run: Callable[[Path], OperationResult]
    destructive: bool = False
    plan: Callable[[Path], OperationResult] | None = None
    visible: bool = True


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


def secret_store_plan(path: Path) -> OperationResult:
    return OperationResult(
        True,
        "Encrypted secret initialization plan",
        (
            f"Age identity: create if absent at {resolve_age_identity_path()}",
            f"Encrypted credentials: create if absent at {resolve_secrets_path()}",
            "SOPS recipient policy: create if absent at the repository root",
            "Existing identities and encrypted credentials will not be replaced",
            "The age identity must be backed up offline after creation",
        ),
    )


def initialize_secret_store(path: Path) -> OperationResult:
    try:
        secret_path, identity_path, recipient, secret_created, identity_created = (
            ensure_secret_store()
        )
    except SecretError as exc:
        return OperationResult(
            False, "Encrypted secret initialization", tuple(str(exc).splitlines())
        )
    return OperationResult(
        True,
        "Encrypted secret initialization",
        (
            f"Age identity: {'created' if identity_created else 'already present'} at {identity_path}",
            f"Public recipient: {recipient}",
            f"Encrypted credentials: {'created' if secret_created else 'already present'} at {secret_path}",
            "Back up the age identity offline before provisioning infrastructure",
        ),
    )


def proxmox_identity_plan(path: Path) -> OperationResult:
    try:
        config = load_config(path)
        plan = build_plan(config)
    except (ConfigurationError, ProxmoxBootstrapError) as exc:
        return OperationResult(False, "Proxmox API identity plan", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Proxmox API identity plan",
        (
            f"SSH private key: {resolve_bootstrap_ssh_key()}",
            "Prerequisite: its public key is authorized for root on the Proxmox host",
            *plan.lines(),
        ),
    )


def proxmox_ssh_plan(path: Path) -> OperationResult:
    return OperationResult(
        True,
        "Proxmox SSH preparation plan",
        (
            f"Dedicated key: create if absent at {resolve_bootstrap_ssh_key()}",
            "Existing private keys will not be replaced",
            "Only the public key will be displayed in the activity log",
            "You will authorize that public key once through the Proxmox console",
        ),
    )


def prepare_proxmox_ssh(path: Path) -> OperationResult:
    try:
        config = load_config(path)
        plan = build_plan(config)
        private_key, public_key, created = ensure_bootstrap_ssh_key()
    except (ConfigurationError, ProxmoxBootstrapError) as exc:
        return OperationResult(False, "Proxmox SSH preparation", tuple(str(exc).splitlines()))
    public_key_path = f"{private_key}.pub"
    copy_command = ("ssh-copy-id", "-i", public_key_path, plan.ssh_target)
    return OperationResult(
        True,
        "Proxmox SSH preparation",
        (
            f"Dedicated SSH key: {'created' if created else 'already present'} at {private_key}",
            f"Target: {plan.ssh_target}",
            "Use the key-install dialog, then run the API identity bootstrap from this menu",
            "If root password SSH is disabled, use the Proxmox console fallback in the dialog",
        ),
        copy_text=shlex.join(copy_command),
        interactive_command=copy_command,
        fallback_text=(
            "install -d -m 700 /root/.ssh && "
            f"printf '%s\\n' {shlex.quote(public_key)} >> /root/.ssh/authorized_keys && "
            "chmod 600 /root/.ssh/authorized_keys"
        ),
    )


def bootstrap_proxmox_identity(path: Path) -> OperationResult:
    try:
        config = load_config(path)
        secret_path, identity_path, _, _, identity_created = ensure_secret_store()
        private_key, _, _ = ensure_bootstrap_ssh_key()
        result = apply_bootstrap(config, secret_path, ssh_private_key=private_key)
    except ProxmoxTokenRecoveryRequired as exc:
        return OperationResult(
            False,
            "Proxmox API token recovery required",
            tuple(str(exc).splitlines()),
            recovery_operation="proxmox-token-recover",
            recovery_prompt=(
                "The named Proxmox token exists, but its usable value is absent from SOPS.\n\n"
                "Recovery will delete only that API token, create its replacement with the same "
                "separated permissions, write the new one-time value directly into SOPS, and "
                "verify API authentication. The role and user will be retained."
            ),
        )
    except (ConfigurationError, ProxmoxBootstrapError, SecretError) as exc:
        return OperationResult(
            False, "Proxmox API identity bootstrap", tuple(str(exc).splitlines())
        )
    action = "created or rotated" if result.created_or_rotated else "reconciled"
    lines = [
        f"API identity {action}: {result.token_id}",
        f"Role reconciled: {result.role_id}",
        f"Encrypted token stored at {secret_path}",
        "Proxmox API authentication verified",
        f"Diagnostic log: {result.diagnostic_log}",
    ]
    if identity_created:
        lines.append(f"New age identity requires an offline backup: {identity_path}")
    return OperationResult(True, "Proxmox API identity bootstrap", tuple(lines))


def recover_proxmox_token(path: Path) -> OperationResult:
    try:
        config = load_config(path)
        secret_path, _, _, _, _ = ensure_secret_store()
        private_key, _, _ = ensure_bootstrap_ssh_key()
        result = apply_bootstrap(
            config,
            secret_path,
            rotate_token=True,
            ssh_private_key=private_key,
        )
    except (ConfigurationError, ProxmoxBootstrapError, SecretError) as exc:
        return OperationResult(False, "Proxmox API token recovery", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Proxmox API token recovery",
        (
            f"API token replaced: {result.token_id}",
            f"Role retained: {result.role_id}",
            f"Replacement token stored at {secret_path}",
            "Replacement token authenticated successfully against the Proxmox API",
            f"Diagnostic log: {result.diagnostic_log}",
        ),
    )


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
        "Inspect the local toolchain, configuration, and encrypted provisioning credentials.",
        system_readiness,
    ),
    Operation(
        "summary",
        "Preview effective settings",
        "Display the exact non-secret values automation will consume.",
        configuration_summary,
    ),
    Operation(
        "secrets-init",
        "Initialize encrypted secrets",
        "Create the age identity, SOPS policy, and encrypted credential store.",
        initialize_secret_store,
        destructive=True,
        plan=secret_store_plan,
    ),
    Operation(
        "proxmox-ssh",
        "Prepare Proxmox SSH access",
        "Create a dedicated key and show the public key to authorize on Proxmox.",
        prepare_proxmox_ssh,
        destructive=True,
        plan=proxmox_ssh_plan,
    ),
    Operation(
        "proxmox-bootstrap",
        "Bootstrap Proxmox API identity",
        "Plan, confirm, and remotely create the Proxmox user, role, ACL, and token.",
        bootstrap_proxmox_identity,
        destructive=True,
        plan=proxmox_identity_plan,
    ),
    Operation(
        "proxmox-token-recover",
        "Recover Proxmox API token",
        "Explicitly replace a remote token whose one-time value is unavailable.",
        recover_proxmox_token,
        destructive=True,
        visible=False,
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
