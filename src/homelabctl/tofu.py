"""Safe OpenTofu foundation checks driven by validated site configuration."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from homelabctl.configuration import find_project_root, load_config
from homelabctl.guard import OperationLockedError, mutation_lock
from homelabctl.models import HomelabConfig, normalize_ssh_public_key
from homelabctl.proxmox_bootstrap import DiagnosticLog
from homelabctl.secrets import load_secrets, resolve_secrets_path


class TofuError(RuntimeError):
    """Raised when the OpenTofu foundation cannot be initialized or checked."""


@dataclass(frozen=True, slots=True)
class TofuCheckResult:
    variables_path: Path
    plan_path: Path
    diagnostic_log: Path
    plan_summary: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TofuApplyResult:
    plan_path: Path
    diagnostic_log: Path


def _plan_metadata_path(plan_path: Path) -> Path:
    return plan_path.with_suffix(f"{plan_path.suffix}.json")


def _configuration_fingerprint(config: HomelabConfig) -> str:
    payload = json.dumps(tofu_variables(config), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _file_fingerprint(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def infrastructure_directory(start: Path | None = None) -> Path:
    return find_project_root(start) / "infrastructure"


def resolved_ssh_public_keys(config: HomelabConfig) -> list[str]:
    """Load configured public-key files and return normalized OpenSSH keys."""

    public_keys = list(config.automation.ssh_public_keys)
    for configured_path in config.automation.ssh_public_key_files:
        path = Path(configured_path).expanduser()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TofuError(f"Unable to read automation SSH public key file: {path}") from exc
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if len(lines) != 1:
            raise TofuError(f"Automation SSH public key file must contain exactly one key: {path}")
        try:
            public_keys.append(normalize_ssh_public_key(lines[0]))
        except ValueError as exc:
            raise TofuError(f"Invalid automation SSH public key file: {path}") from exc
    if len(public_keys) != len(set(public_keys)):
        raise TofuError("Automation SSH public keys resolve to duplicate values")
    return sorted(public_keys)


def tofu_variables(config: HomelabConfig) -> dict[str, object]:
    """Map strict application configuration into the OpenTofu input contract."""

    return {
        "site": {
            "name": config.site.name,
            "domain": config.site.domain,
            "timezone": config.site.timezone,
            "environment": config.site.environment,
        },
        "proxmox": {
            "endpoint": str(config.proxmox.api_url),
            "node": config.proxmox.node,
            "storage": config.proxmox.storage,
            "token_id": config.proxmox.token_id,
            "insecure": not config.proxmox.verify_tls,
        },
        "network": {
            "management_cidr": str(config.network.management_cidr),
            "gateway": str(config.network.gateway),
            "dns_servers": [str(address) for address in config.network.dns_servers],
            "bridge": config.network.bridge,
            "vlan_id": config.network.vlan_id,
        },
        "automation": {
            "ssh_public_keys": resolved_ssh_public_keys(config),
        },
        "cloudflare_domains": config.cloudflare.domains,
        "proxmox_lxcs": [
            {
                "key": container.key,
                "vm_id": container.vm_id,
                "hostname": container.hostname,
                "template_file_id": container.template_file_id,
                "address": str(container.address),
                "cores": container.cores,
                "memory_mb": container.memory_mb,
                "swap_mb": container.swap_mb,
                "disk_gb": container.disk_gb,
                "started": container.started,
                "start_on_boot": container.start_on_boot,
                "nesting": container.nesting,
                "protection": container.protection,
                "tags": container.tags,
            }
            for container in sorted(config.proxmox.containers, key=lambda item: item.key)
            if container.provisioner == "opentofu"
        ],
        "cloudflare_records": [
            {
                "zone": record.zone,
                "name": record.name,
                "type": record.type,
                "content": record.content,
                "ttl": record.ttl,
                "proxied": record.proxied,
            }
            for record in sorted(config.cloudflare.records, key=lambda item: item.resource_key)
        ],
    }


def write_tofu_variables(config: HomelabConfig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tofu_variables(config), indent=2) + "\n", encoding="utf-8")
    return path


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    diagnostic: DiagnosticLog,
    accepted_codes: tuple[int, ...] = (0,),
    timeout: int = 180,
) -> str:
    diagnostic.write("tofu.execute", " ".join(command))
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        diagnostic.write("tofu.exception", f"{type(exc).__name__}: {exc}")
        raise TofuError(f"Unable to run OpenTofu. Diagnostic log: {diagnostic.path}") from exc
    diagnostic.write("tofu.result", f"exit_code={completed.returncode}")
    safe_stdout: list[str] = []
    for stream, content in (("stdout", completed.stdout), ("stderr", completed.stderr)):
        for line in content.splitlines():
            safe_line = line
            runtime_tokens = {
                environment.get("TF_VAR_proxmox_api_token", ""),
                environment.get("PROXMOX_VE_API_TOKEN", ""),
                environment.get("CLOUDFLARE_API_TOKEN", ""),
            }
            for runtime_token in runtime_tokens - {""}:
                safe_line = safe_line.replace(runtime_token, "[REDACTED]")
            diagnostic.write(f"tofu.{stream}", safe_line)
            if stream == "stdout":
                safe_stdout.append(safe_line)
    if completed.returncode not in accepted_codes:
        raise TofuError(
            f"OpenTofu check failed while running: {' '.join(command[1:3])}. "
            f"Diagnostic log: {diagnostic.path}"
        )
    return "\n".join(safe_stdout)


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def summarize_plan(output: str) -> tuple[str, ...]:
    """Return resource-level actions safe for an operator confirmation dialog."""

    lines = [_ANSI_ESCAPE.sub("", line).strip() for line in output.splitlines()]
    resource_actions = [
        line.removeprefix("# ")
        for line in lines
        if line.startswith("# ") and (" will be " in line or " must be replaced" in line)
    ]
    totals = next((line for line in lines if line.startswith("Plan: ")), None)
    no_changes = any(line.startswith("No changes.") for line in lines)
    output_only = any("without changing any real infrastructure" in line for line in lines)

    summary = ["Infrastructure resources in this plan:"]
    summary.extend(f"- {action}" for action in resource_actions)
    if totals:
        summary.append(totals)
    elif no_changes:
        summary.append("No infrastructure resources will change.")
    elif output_only or not resource_actions:
        summary.append("Resources: 0 to add, 0 to change, 0 to destroy.")
        if output_only:
            summary.append("Only OpenTofu output values will be recorded.")
    return tuple(summary)


def summarize_desired_infrastructure(config: HomelabConfig) -> tuple[str, ...]:
    """Describe the exact secret-free infrastructure target in operator language."""

    summary = ["Configured infrastructure target:"]
    if config.proxmox.containers:
        for container in sorted(config.proxmox.containers, key=lambda item: item.key):
            owner = "OpenTofu" if container.provisioner == "opentofu" else "Community Scripts"
            summary.append(
                f'- {owner} LXC "{container.hostname}": VMID {container.vm_id}, '
                f"{container.address}, {container.cores} vCPU, {container.memory_mb} MiB RAM, "
                f"{container.disk_gb} GiB disk"
            )
    else:
        summary.append("- Proxmox LXCs: none configured")

    if config.cloudflare.records:
        for record in sorted(config.cloudflare.records, key=lambda item: item.resource_key):
            name = record.zone if record.name == "@" else f"{record.name}.{record.zone}"
            exposure = "proxied" if record.proxied else "DNS only"
            summary.append(
                f"- Cloudflare {record.type} record: {name} -> {record.content} ({exposure})"
            )
    else:
        summary.append("- Cloudflare DNS records: none configured")
    return tuple(summary)


def _runtime_environment(
    root: Path, config: HomelabConfig, secrets_path: str | Path | None
) -> dict[str, str]:
    bundle = load_secrets(resolve_secrets_path(secrets_path), config=config)
    environment = os.environ.copy()
    environment["TF_IN_AUTOMATION"] = "1"
    environment["TF_INPUT"] = "0"
    environment["TF_DATA_DIR"] = str(root / ".cache" / "tofu" / "data")
    environment.update(bundle.provider_environment())
    environment["TF_VAR_proxmox_api_token"] = bundle.proxmox.api_token.get_secret_value()
    return environment


def check_foundation(
    config_path: str | Path,
    secrets_path: str | Path | None = None,
    *,
    tofu_executable: str | None = None,
) -> TofuCheckResult:
    """Initialize, validate, and create a non-destructive saved plan."""

    tofu = tofu_executable or shutil.which("tofu")
    if not tofu:
        raise TofuError("OpenTofu is not installed or is not on PATH")
    config = load_config(config_path)
    root = find_project_root(Path(config_path).resolve().parent)
    working = infrastructure_directory(root)
    variables_path = write_tofu_variables(
        config, root / ".cache" / "tofu" / "site.auto.tfvars.json"
    )
    plan_path = root / "artifacts" / "foundation.tfplan"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic = DiagnosticLog(root / "logs" / "opentofu.log")
    environment = _runtime_environment(root, config, secrets_path)

    diagnostic.write("tofu.check.start", f"working_directory={working}")
    _run(
        [tofu, "fmt", "-check", "-recursive"],
        cwd=working,
        environment=environment,
        diagnostic=diagnostic,
    )
    init_command = [tofu, "init", "-reconfigure", "-input=false", "-lockfile=readonly"]
    production_backend = working / "backend.production.tf"
    production_backend_config = working / "backend.production.hcl"
    if production_backend.exists():
        if not production_backend_config.is_file():
            raise TofuError(
                "Production backend is enabled but backend.production.hcl is missing. "
                f"Diagnostic log: {diagnostic.path}"
            )
        init_command.append(f"-backend-config={production_backend_config}")
        diagnostic.write("tofu.backend", "production S3-compatible backend with locking")
    else:
        diagnostic.write("tofu.backend", "local development backend")
    _run(init_command, cwd=working, environment=environment, diagnostic=diagnostic)
    _run([tofu, "validate"], cwd=working, environment=environment, diagnostic=diagnostic)
    plan_output = _run(
        [
            tofu,
            "plan",
            "-refresh=false",
            "-lock=true",
            "-lock-timeout=30s",
            "-input=false",
            f"-var-file={variables_path}",
            f"-out={plan_path}",
            "-detailed-exitcode",
        ],
        cwd=working,
        environment=environment,
        diagnostic=diagnostic,
        accepted_codes=(0, 2),
    )
    if not plan_path.is_file():
        raise TofuError(f"OpenTofu did not create the expected saved plan: {plan_path}")
    metadata = {
        "format": 1,
        "configuration_sha256": _configuration_fingerprint(config),
        "plan_sha256": _file_fingerprint(plan_path),
    }
    _plan_metadata_path(plan_path).write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    diagnostic.write("tofu.check.complete", "format, initialization, validation, and plan passed")
    return TofuCheckResult(
        variables_path,
        plan_path,
        diagnostic.path,
        (*summarize_desired_infrastructure(config), *summarize_plan(plan_output)),
    )


def apply_saved_plan(
    config_path: str | Path,
    secrets_path: str | Path | None = None,
    *,
    tofu_executable: str | None = None,
) -> TofuApplyResult:
    """Apply only the existing saved plan with decrypted runtime provider credentials."""

    tofu = tofu_executable or shutil.which("tofu")
    if not tofu:
        raise TofuError("OpenTofu is not installed or is not on PATH")
    config = load_config(config_path)
    root = find_project_root(Path(config_path).resolve().parent)
    working = infrastructure_directory(root)
    plan_path = root / "artifacts" / "foundation.tfplan"
    if not plan_path.is_file():
        raise TofuError(f"Saved OpenTofu plan not found: {plan_path}. Run `task tofu:check` first.")
    metadata_path = _plan_metadata_path(plan_path)
    if not metadata_path.is_file():
        raise TofuError("Saved OpenTofu plan provenance is missing; create and review a new plan")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TofuError("Saved OpenTofu plan provenance is invalid; create a new plan") from exc
    if metadata.get("configuration_sha256") != _configuration_fingerprint(config):
        raise TofuError("Site configuration changed after planning; create and review a new plan")
    if metadata.get("plan_sha256") != _file_fingerprint(plan_path):
        raise TofuError("Saved OpenTofu plan changed after planning; create and review a new plan")

    diagnostic = DiagnosticLog(root / "logs" / "opentofu.log")
    environment = _runtime_environment(root, config, secrets_path)
    diagnostic.write("tofu.apply.start", f"saved_plan={plan_path}")
    try:
        with mutation_lock(root, "OpenTofu apply"):
            _run(
                [
                    tofu,
                    "apply",
                    "-lock=true",
                    "-lock-timeout=30s",
                    "-input=false",
                    str(plan_path),
                ],
                cwd=working,
                environment=environment,
                diagnostic=diagnostic,
                timeout=3600,
            )
    except OperationLockedError as exc:
        raise TofuError(str(exc)) from exc
    diagnostic.write("tofu.apply.complete", "reviewed saved plan applied")
    return TofuApplyResult(plan_path, diagnostic.path)
