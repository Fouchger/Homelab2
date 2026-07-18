"""Safe operations exposed by the control-panel menu."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from homelabctl.ansible import AnsibleError, generate_inventory, run_baseline
from homelabctl.ansible_setup import (
    AnsibleSetupError,
    install_ansible_prerequisites,
    setup_plan,
)
from homelabctl.applications import (
    ApplicationError,
    application_plan,
    run_applications,
)
from homelabctl.automation_ssh import (
    AutomationSshError,
    ensure_automation_ssh_key,
    resolve_automation_ssh_key,
)
from homelabctl.configuration import (
    ConfigurationError,
    find_project_root,
    load_config,
    redacted_mapping,
    resolve_config_path,
    save_config,
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
    masked_provider_secret_hint,
    resolve_age_identity_path,
    resolve_secrets_path,
    set_cloudflare_token,
    validate_provider_secret,
)
from homelabctl.tofu import TofuError, apply_saved_plan, check_foundation
from homelabctl.updater import UpdateError, apply_update, prepare_update


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
    secret_hint: str | None = None


@dataclass(frozen=True, slots=True)
class Operation:
    identifier: str
    title: str
    description: str
    run: Callable[[Path], OperationResult]
    section: str = "setup"
    destructive: bool = False
    plan: Callable[[Path], OperationResult] | None = None
    visible: bool = True
    secret_prompt: str | None = None
    sequence: int = 0


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


def ansible_setup_plan(path: Path) -> OperationResult:
    try:
        lines = setup_plan(path)
    except AnsibleSetupError as exc:
        return OperationResult(False, "Install Ansible prerequisites", tuple(str(exc).splitlines()))
    return OperationResult(True, "Install Ansible prerequisites", lines)


def setup_ansible(path: Path) -> OperationResult:
    try:
        result = install_ansible_prerequisites(path)
    except AnsibleSetupError as exc:
        return OperationResult(False, "Install Ansible prerequisites", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Install Ansible prerequisites",
        (
            f"Ansible playbook: {result.ansible_playbook}",
            f"Ansible Galaxy: {result.ansible_galaxy}",
            "Locked collections installed",
            f"Diagnostic log: {result.diagnostic_log}",
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


def control_plane_update_plan(path: Path) -> OperationResult:
    try:
        plan = prepare_update(find_project_root(path.parent))
    except UpdateError as exc:
        return OperationResult(False, "Control-plane update plan", tuple(str(exc).splitlines()))
    if plan.up_to_date:
        lines = (
            f"Current version: {plan.current_commit[:12]}",
            "GitHub version: already current",
            "No source files will change",
        )
    else:
        displayed = plan.changed_files[:8]
        remainder = len(plan.changed_files) - len(displayed)
        lines = (
            f"Current version: {plan.current_commit[:12]}",
            f"Available version: {plan.target_commit[:12]}",
            f"Changed files ({len(plan.changed_files)}): {', '.join(displayed)}"
            + (f" and {remainder} more" if remainder else ""),
            "Only a clean fast-forward update is allowed",
            "Local configuration, encrypted secrets, state, logs, and age keys are preserved",
            "Restart the menu after updating to load the new code",
        )
    return OperationResult(True, "Control-plane update plan", lines)


def update_control_plane(path: Path) -> OperationResult:
    try:
        result = apply_update(find_project_root(path.parent))
    except UpdateError as exc:
        return OperationResult(False, "Control-plane update", tuple(str(exc).splitlines()))
    if result.updated:
        lines = (
            f"Updated {result.previous_commit[:12]} to {result.current_commit[:12]}",
            f"Updated files: {len(result.changed_files)}",
            "Locked Python environment synchronized",
            "Exit and reopen the menu now to load the updated control plane",
            f"Diagnostic log: {result.diagnostic_log}",
        )
    else:
        lines = (
            f"Already current at {result.current_commit[:12]}",
            "No files were changed",
            f"Diagnostic log: {result.diagnostic_log}",
        )
    return OperationResult(True, "Control-plane update", lines)


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


def cloudflare_token_plan(path: Path) -> OperationResult:
    try:
        config = load_config(path)
    except ConfigurationError as exc:
        return OperationResult(False, "Cloudflare token plan", tuple(str(exc).splitlines()))
    if not config.cloudflare.domains:
        return OperationResult(
            False,
            "Cloudflare token plan",
            ("No external Cloudflare domains are configured.",),
        )
    try:
        hint = masked_provider_secret_hint(resolve_secrets_path(), "cloudflare")
    except SecretError:
        hint = None
    token_status = (
        "Existing Cloudflare token: validated and available to keep"
        if hint is not None
        else "Existing Cloudflare token: not available; enter a replacement"
    )
    return OperationResult(
        True,
        "Cloudflare token plan",
        (
            f"Domains: {', '.join(config.cloudflare.domains)}",
            f"Encrypted credentials: {resolve_secrets_path()}",
            token_status,
            "Existing token values are never written to the activity log",
            "The Cloudflare credential will be validated independently after saving",
        ),
        secret_hint=hint,
    )


def confirm_cloudflare_credential(path: Path) -> OperationResult:
    try:
        config = load_config(path)
        secret_path = resolve_secrets_path()
        validate_provider_secret(secret_path, "cloudflare")
    except (ConfigurationError, SecretError) as exc:
        return OperationResult(False, "Cloudflare API token", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Cloudflare API token",
        (
            f"Existing encrypted Cloudflare credential confirmed at {secret_path}",
            f"Cloudflare credential validated for {len(config.cloudflare.domains)} configured domain(s)",
            "The encrypted token was kept unchanged",
        ),
    )


def set_cloudflare_credential(path: Path, token: str) -> OperationResult:
    try:
        config = load_config(path)
        secret_path = set_cloudflare_token(resolve_secrets_path(), token)
        validate_provider_secret(secret_path, "cloudflare")
    except (ConfigurationError, SecretError) as exc:
        return OperationResult(False, "Cloudflare API token", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Cloudflare API token",
        (
            f"Encrypted Cloudflare token stored at {secret_path}",
            f"Cloudflare credential validated for {len(config.cloudflare.domains)} configured domain(s)",
            "Proxmox credentials can be completed separately from the Proxmox menu",
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


def check_tofu_foundation(path: Path) -> OperationResult:
    try:
        result = check_foundation(path)
    except (ConfigurationError, SecretError, TofuError) as exc:
        return OperationResult(False, "OpenTofu foundation check", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "OpenTofu foundation check",
        (
            "OpenTofu formatting passed",
            "Provider lock initialization passed",
            "OpenTofu configuration validation passed",
            f"Non-destructive plan saved at {result.plan_path}",
            f"Generated non-secret inputs: {result.variables_path}",
            f"Diagnostic log: {result.diagnostic_log}",
        ),
    )


def apply_tofu_foundation(path: Path) -> OperationResult:
    try:
        result = apply_saved_plan(path)
    except (ConfigurationError, SecretError, TofuError) as exc:
        return OperationResult(False, "Apply OpenTofu plan", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Apply OpenTofu plan",
        (
            f"Applied reviewed plan: {result.plan_path}",
            f"Diagnostic log: {result.diagnostic_log}",
        ),
    )


def preview_guest_inventory(path: Path) -> OperationResult:
    try:
        inventory, hosts = generate_inventory(path)
    except (AnsibleError, ConfigurationError) as exc:
        return OperationResult(False, "Guest automation inventory", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Guest automation inventory",
        (*hosts, f"Runtime inventory: {inventory}"),
    )


def check_guest_baseline(path: Path) -> OperationResult:
    try:
        result = run_baseline(path, check=True)
    except (AnsibleError, ConfigurationError) as exc:
        return OperationResult(False, "Guest baseline preview", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Guest baseline preview",
        (
            *result.lines,
            "No guest changes were applied",
            f"Diagnostic log: {result.diagnostic_log}",
        ),
    )


def apply_guest_baseline(path: Path) -> OperationResult:
    try:
        result = run_baseline(path, check=False)
    except (AnsibleError, ConfigurationError) as exc:
        return OperationResult(False, "Guest baseline apply", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Guest baseline apply",
        (*result.lines, f"Diagnostic log: {result.diagnostic_log}"),
    )


def preview_curated_applications(path: Path) -> OperationResult:
    try:
        lines = application_plan(path)
        result = run_applications(path, check=True)
    except (ApplicationError, ConfigurationError) as exc:
        return OperationResult(False, "Curated application preview", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Curated application preview",
        (*lines, *result.lines, "No application changes were applied"),
    )


def apply_curated_applications(path: Path) -> OperationResult:
    try:
        result = run_applications(path, check=False)
    except (ApplicationError, ConfigurationError) as exc:
        return OperationResult(False, "Curated application apply", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Curated application apply",
        (
            *result.lines,
            f"Health check passed on guest {result.guest}",
            f"Diagnostic log: {result.diagnostic_log}",
        ),
    )


def automation_ssh_plan(path: Path) -> OperationResult:
    try:
        config = load_config(path)
    except ConfigurationError as exc:
        return OperationResult(False, "Guest automation SSH key plan", tuple(str(exc).splitlines()))
    private_key = resolve_automation_ssh_key(config.automation.ssh_private_key)
    return OperationResult(
        True,
        "Guest automation SSH key plan",
        (
            f"Private key: create if absent at {private_key}",
            f"Public key: create at {private_key}.pub",
            "Key type: Ed25519 without a passphrase for unattended automation",
            "Existing complete key pairs will be verified and never replaced",
            "Incomplete or mismatched key pairs will be rejected",
            "The public-key path will be added to the site configuration if absent",
            "Private key material will never be displayed or logged",
        ),
    )


def prepare_automation_ssh(path: Path) -> OperationResult:
    try:
        config = load_config(path)
        key = ensure_automation_ssh_key(config.automation.ssh_private_key)
        configured_public_key = f"{config.automation.ssh_private_key}.pub"
        already_configured = any(
            Path(item).expanduser().resolve() == key.public_key
            for item in config.automation.ssh_public_key_files
        )
        if not already_configured:
            config.automation.ssh_public_key_files = [
                *config.automation.ssh_public_key_files,
                configured_public_key,
            ]
            save_config(config, path)
    except (AutomationSshError, ConfigurationError) as exc:
        return OperationResult(False, "Guest automation SSH key", tuple(str(exc).splitlines()))
    return OperationResult(
        True,
        "Guest automation SSH key",
        (
            f"Private key: {'created' if key.created else 'already present'} at {key.private_key}",
            f"Public key: verified at {key.public_key}",
            f"Fingerprint: {key.fingerprint}",
            (
                "Site configuration: public-key path already present"
                if already_configured
                else f"Site configuration: added {configured_public_key}"
            ),
            "The key is ready for OpenTofu guest provisioning",
        ),
    )


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "validate",
        "Validate configuration",
        "Check every site value and reject unknown or unsafe settings.",
        validate_configuration,
        sequence=10,
    ),
    Operation(
        "ansible-setup",
        "Install Ansible prerequisites",
        "Install ansible-core and the repository's locked collections on this control plane.",
        setup_ansible,
        section="setup",
        destructive=True,
        plan=ansible_setup_plan,
        sequence=20,
    ),
    Operation(
        "doctor",
        "Check system readiness",
        "Inspect the local toolchain, configuration, and encrypted provisioning credentials.",
        system_readiness,
        section="diagnostics",
        sequence=10,
    ),
    Operation(
        "summary",
        "Preview effective settings",
        "Display the exact non-secret values automation will consume.",
        configuration_summary,
        section="diagnostics",
        sequence=20,
    ),
    Operation(
        "update",
        "Update control plane",
        "Safely fetch and install the latest fast-forward version from GitHub.",
        update_control_plane,
        section="maintenance",
        destructive=True,
        plan=control_plane_update_plan,
        sequence=10,
    ),
    Operation(
        "secrets-init",
        "Initialize encrypted secrets",
        "Create the age identity, SOPS policy, and encrypted credential store.",
        initialize_secret_store,
        destructive=True,
        plan=secret_store_plan,
        sequence=30,
    ),
    Operation(
        "cloudflare-token",
        "Set Cloudflare API token",
        "Confirm, add, or replace the token required by configured external domains.",
        confirm_cloudflare_credential,
        destructive=True,
        plan=cloudflare_token_plan,
        secret_prompt="Paste the scoped Cloudflare API token. The value stays masked and is sent directly to SOPS.",
        sequence=40,
    ),
    Operation(
        "proxmox-ssh",
        "Prepare Proxmox SSH access",
        "Create a dedicated key and show the public key to authorize on Proxmox.",
        prepare_proxmox_ssh,
        section="proxmox",
        destructive=True,
        plan=proxmox_ssh_plan,
        sequence=10,
    ),
    Operation(
        "proxmox-bootstrap",
        "Bootstrap Proxmox API identity",
        "Plan, confirm, and remotely create the Proxmox user, role, ACL, and token.",
        bootstrap_proxmox_identity,
        section="proxmox",
        destructive=True,
        plan=proxmox_identity_plan,
        sequence=20,
    ),
    Operation(
        "proxmox-token-recover",
        "Recover Proxmox API token",
        "Explicitly replace a remote token whose one-time value is unavailable.",
        recover_proxmox_token,
        section="proxmox",
        destructive=True,
        visible=False,
        sequence=30,
    ),
    Operation(
        "automation-ssh",
        "Prepare guest automation SSH key",
        "Create and configure the dedicated key used to bootstrap managed guests.",
        prepare_automation_ssh,
        section="infrastructure",
        destructive=True,
        plan=automation_ssh_plan,
        sequence=10,
    ),
    Operation(
        "tofu-check",
        "Check OpenTofu foundation",
        "Initialize locked providers, validate typed inputs, and create a non-destructive plan.",
        check_tofu_foundation,
        section="infrastructure",
        sequence=20,
    ),
    Operation(
        "tofu-apply",
        "Apply reviewed OpenTofu plan",
        "Create a fresh plan, confirm it, and apply that exact provenance-checked plan.",
        apply_tofu_foundation,
        section="infrastructure",
        destructive=True,
        plan=check_tofu_foundation,
        sequence=30,
    ),
    Operation(
        "ansible-inventory",
        "Preview guest inventory",
        "Derive a secret-free runtime inventory from the accepted OpenTofu state.",
        preview_guest_inventory,
        section="infrastructure",
        sequence=40,
    ),
    Operation(
        "ansible-check",
        "Preview guest baseline",
        "Run the Debian-family baseline in Ansible check mode without changing guests.",
        check_guest_baseline,
        section="infrastructure",
        sequence=50,
    ),
    Operation(
        "ansible-apply",
        "Apply guest baseline",
        "Preview, confirm, and apply the baseline to provisioned guests one at a time.",
        apply_guest_baseline,
        section="infrastructure",
        destructive=True,
        plan=check_guest_baseline,
        sequence=60,
    ),
    Operation(
        "applications-check",
        "Preview curated applications",
        "Verify pinned snapshots and preview in-guest application changes.",
        preview_curated_applications,
        section="infrastructure",
        sequence=70,
    ),
    Operation(
        "applications-apply",
        "Apply curated applications",
        "Preview, confirm, install, and health-check approved application snapshots.",
        apply_curated_applications,
        section="infrastructure",
        destructive=True,
        plan=preview_curated_applications,
        sequence=80,
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


def execute_with_secret(
    identifier: str, secret: str, path: str | Path | None = None
) -> OperationResult:
    if identifier != "cloudflare-token":
        raise KeyError(f"Operation does not accept secret input: {identifier}")
    return set_cloudflare_credential(resolve_config_path(path), secret)
