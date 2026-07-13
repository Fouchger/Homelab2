"""Safe OpenTofu foundation checks driven by validated site configuration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from homelabctl.configuration import find_project_root, load_config
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
) -> None:
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
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        diagnostic.write("tofu.exception", f"{type(exc).__name__}: {exc}")
        raise TofuError(f"Unable to run OpenTofu. Diagnostic log: {diagnostic.path}") from exc
    diagnostic.write("tofu.result", f"exit_code={completed.returncode}")
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
    if completed.returncode not in accepted_codes:
        raise TofuError(
            f"OpenTofu check failed while running: {' '.join(command[1:3])}. "
            f"Diagnostic log: {diagnostic.path}"
        )


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
    bundle = load_secrets(resolve_secrets_path(secrets_path), config=config)
    root = find_project_root(Path(config_path).resolve().parent)
    working = infrastructure_directory(root)
    variables_path = write_tofu_variables(
        config, root / ".cache" / "tofu" / "site.auto.tfvars.json"
    )
    plan_path = root / "artifacts" / "foundation.tfplan"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic = DiagnosticLog(root / "logs" / "opentofu.log")
    environment = os.environ.copy()
    environment["TF_IN_AUTOMATION"] = "1"
    environment["TF_INPUT"] = "0"
    environment["TF_DATA_DIR"] = str(root / ".cache" / "tofu" / "data")
    environment.update(bundle.provider_environment())
    environment["TF_VAR_proxmox_api_token"] = bundle.proxmox.api_token.get_secret_value()

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
    _run(
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
    diagnostic.write("tofu.check.complete", "format, initialization, validation, and plan passed")
    return TofuCheckResult(variables_path, plan_path, diagnostic.path)
