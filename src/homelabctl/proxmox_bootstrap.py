"""Idempotent Proxmox API identity bootstrap over an administrator SSH connection."""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from homelabctl.models import HomelabConfig
from homelabctl.secrets import (
    SecretError,
    SecretPlaceholderError,
    load_secrets,
    set_proxmox_token,
)

DEFAULT_ROLE_ID = "HomelabProvisioner"
DEFAULT_BOOTSTRAP_SSH_KEY = Path("~/.ssh/proxmox_bootstrap_ed25519")
DEFAULT_DIAGNOSTIC_LOG = Path("logs/proxmox-bootstrap.log")
TOKEN_ID_PATTERN = re.compile(
    r"^(?P<user>[a-z_][a-z0-9_.-]{0,31})@(?P<realm>[a-z][a-z0-9_.-]{0,31})!"
    r"(?P<token>[a-zA-Z0-9_.-]{1,63})$"
)
ROLE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,63}$")
SSH_TARGET_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+$")

# Initial VM/LXC profile only. Add privileges deliberately when issue #6 adds a resource that needs
# one. In particular, Sys.Modify, Permissions.Modify, and user-management privileges are excluded.
PROVISIONING_PRIVILEGES: tuple[str, ...] = (
    "Datastore.AllocateSpace",
    "Datastore.AllocateTemplate",
    "Datastore.Audit",
    "SDN.Use",
    "Sys.Audit",
    "VM.Allocate",
    "VM.Audit",
    "VM.Clone",
    "VM.Config.CDROM",
    "VM.Config.CPU",
    "VM.Config.Cloudinit",
    "VM.Config.Disk",
    "VM.Config.HWType",
    "VM.Config.Memory",
    "VM.Config.Network",
    "VM.Config.Options",
    "VM.Migrate",
    "VM.PowerMgmt",
)

REMOTE_BOOTSTRAP_SCRIPT = r"""#!/usr/bin/env bash
set -Eeuo pipefail

user_id="$1"
role_id="$2"
token_name="$3"
rotate_token="$4"
privileges="$5"
privileges="${privileges//,/ }"
full_token_id="${user_id}!${token_name}"

exec 2> >(sed 's/^/HOMELAB_BOOTSTRAP: /' >&2)
info() { printf '==> %s\n' "$*" >&2; }
json_field_exists() {
  local field="$1"
  local expected="$2"
  FIELD="$field" EXPECTED="$expected" perl -MJSON::PP -0777 -e '
    my $items = decode_json(<STDIN>);
    for my $item (@{$items}) {
      exit 0 if defined($item->{$ENV{FIELD}}) && $item->{$ENV{FIELD}} eq $ENV{EXPECTED};
    }
    exit 1;
  '
}

[ "$(id -u)" -eq 0 ] || { printf 'root access is required\n' >&2; exit 1; }
command -v pveum >/dev/null 2>&1 || { printf 'pveum is not available\n' >&2; exit 1; }
perl -MJSON::PP -e 1 >/dev/null 2>&1 || { printf 'Perl JSON::PP is not available\n' >&2; exit 1; }
info "Connected to Proxmox host $(hostname)"
if command -v pveversion >/dev/null 2>&1; then
  info "Version $(pveversion | head -n 1)"
fi

if pveum role list --output-format json | json_field_exists roleid "$role_id"; then
  info "Reconciling role ${role_id}"
  pveum role modify "$role_id" -privs "$privileges"
else
  info "Creating role ${role_id}"
  pveum role add "$role_id" -privs "$privileges"
fi

if pveum user list --output-format json | json_field_exists userid "$user_id"; then
  info "Reconciling user ${user_id}"
  pveum user modify "$user_id" -enable 1 -comment "Managed by Homelab Control Plane"
else
  info "Creating user ${user_id}"
  pveum user add "$user_id" -enable 1 -comment "Managed by Homelab Control Plane"
fi

# With privilege separation enabled, token permissions are the intersection of the backing user's
# ACL and the token's ACL. Apply the same narrow role to both subjects.
pveum acl modify / -user "$user_id" -role "$role_id" -propagate 1

token_exists=0
if pveum user token list "$user_id" --output-format json | json_field_exists tokenid "$token_name"; then
  token_exists=1
fi

if [ "$token_exists" -eq 1 ] && [ "$rotate_token" -ne 1 ]; then
  pveum acl modify / -token "$full_token_id" -role "$role_id" -propagate 1
  pveum user token permissions "$user_id" "$token_name" >/dev/null
  printf '{"status":"existing"}\n'
  exit 0
fi

if [ "$token_exists" -eq 1 ]; then
  info "Rotating token ${full_token_id}"
  pveum user token remove "$user_id" "$token_name"
else
  info "Creating token ${full_token_id}"
fi

token_json="$(pveum user token add "$user_id" "$token_name" -privsep 1 --output-format json)"
pveum acl modify / -token "$full_token_id" -role "$role_id" -propagate 1
pveum user token permissions "$user_id" "$token_name" >/dev/null
printf '%s\n' "$token_json"
"""


class ProxmoxBootstrapError(RuntimeError):
    """Raised when the Proxmox identity cannot be planned, created, or verified."""

    def __init__(self, message: str, *, diagnostic_log: Path | None = None) -> None:
        self.diagnostic_log = diagnostic_log
        suffix = f"\nDiagnostic log: {diagnostic_log}" if diagnostic_log is not None else ""
        super().__init__(message + suffix)


class ProxmoxTokenRecoveryRequired(ProxmoxBootstrapError):
    """Raised when a token exists remotely but its one-time value was never captured."""


SECRET_TOKEN_PATTERN = re.compile(r"([A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+=)[^\s\"']+")
JSON_VALUE_PATTERN = re.compile(r'("value"\s*:\s*")[^"]+(\")', re.IGNORECASE)
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
SSH_ERROR_MARKERS = (
    "Permission denied",
    "Could not resolve hostname",
    "Connection refused",
    "Connection timed out",
    "Host key verification failed",
    "Identity file",
    "No route to host",
    "Connection closed",
    "Connection reset",
)


def resolve_diagnostic_log_path(path: str | Path | None = None) -> Path:
    configured = os.environ.get("HOMELAB_DIAGNOSTIC_LOG")
    return Path(path or configured or DEFAULT_DIAGNOSTIC_LOG).expanduser().resolve()


def redact_diagnostic_text(value: str) -> str:
    """Remove known credential shapes before diagnostic text reaches persistent storage."""

    value = SECRET_TOKEN_PATTERN.sub(r"\1[REDACTED]", value)
    value = JSON_VALUE_PATTERN.sub(r"\1[REDACTED]\2", value)
    value = UUID_PATTERN.sub("[REDACTED]", value)
    value = re.sub(
        r"(Authorization\s*:\s*PVEAPIToken=)[^\s]+",
        r"\1[REDACTED]",
        value,
        flags=re.IGNORECASE,
    )
    return value


class DiagnosticLog:
    """Append-only, local, secret-redacted diagnostics for bootstrap troubleshooting."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = resolve_diagnostic_log_path(path)

    def write(self, event: str, detail: str = "") -> None:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        safe_detail = redact_diagnostic_text(detail).replace("\x00", "")
        line = f"{timestamp} {event}"
        if safe_detail:
            line += f" | {safe_detail}"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line.rstrip() + "\n")
            if os.name != "nt":
                self.path.chmod(0o600)
        except OSError:
            # Diagnostics must never prevent or change the provisioning operation.
            return


def safe_remote_diagnostics(stderr: str, *, limit: int | None = 12) -> tuple[str, ...]:
    """Return only redacted bootstrap/SSH diagnostics, never arbitrary protected output."""

    safe_lines: list[str] = []
    for raw_line in stderr.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("HOMELAB_BOOTSTRAP:") and not any(
            marker in line for marker in SSH_ERROR_MARKERS
        ):
            continue
        line = redact_diagnostic_text(line)
        safe_lines.append(line[:500])
    return tuple(safe_lines[-limit:] if limit is not None else safe_lines)


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    ssh_target: str
    user_id: str
    role_id: str
    token_name: str
    token_id: str
    privileges: tuple[str, ...]
    rotate_token: bool

    def lines(self) -> tuple[str, ...]:
        action = (
            "Rotate explicitly after reconciliation" if self.rotate_token else "Keep if present"
        )
        return (
            f"Administrator connection: {self.ssh_target}",
            f"User: create or reconcile {self.user_id}",
            f"Role: create or reconcile {self.role_id}",
            "ACL: assign the role to both user and separated token at /",
            f"Token: {self.token_id} ({action})",
            f"Privileges ({len(self.privileges)}): {', '.join(self.privileges)}",
            "Secret handling: write the one-time token value directly into SOPS",
            "Verification: authenticate to the Proxmox /version API before reporting success",
        )


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    created_or_rotated: bool
    token_id: str
    role_id: str
    diagnostic_log: Path


def resolve_bootstrap_ssh_key(path: str | Path | None = None) -> Path:
    configured = os.environ.get("HOMELAB_PROXMOX_SSH_KEY")
    return Path(path or configured or DEFAULT_BOOTSTRAP_SSH_KEY).expanduser().resolve()


def ensure_bootstrap_ssh_key(
    path: str | Path | None = None, *, ssh_keygen_executable: str | None = None
) -> tuple[Path, str, bool]:
    """Create a dedicated administrator bootstrap key and return only its public half."""

    private_key = resolve_bootstrap_ssh_key(path)
    public_key = Path(f"{private_key}.pub")
    ssh_keygen = ssh_keygen_executable or shutil.which("ssh-keygen")
    if not ssh_keygen:
        raise ProxmoxBootstrapError("ssh-keygen is not installed or is not on PATH")
    created = False
    if not private_key.exists():
        private_key.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            private_key.parent.chmod(0o700)
        try:
            completed = subprocess.run(
                [
                    ssh_keygen,
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    "homelab-control-plane-proxmox-bootstrap",
                    "-f",
                    str(private_key),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProxmoxBootstrapError("Unable to create the Proxmox bootstrap SSH key") from exc
        if completed.returncode != 0 or not private_key.is_file() or not public_key.is_file():
            raise ProxmoxBootstrapError("Unable to create the Proxmox bootstrap SSH key")
        if os.name != "nt":
            private_key.chmod(0o600)
            public_key.chmod(0o644)
        created = True
    if not public_key.is_file():
        raise ProxmoxBootstrapError(f"Public key is missing for bootstrap identity: {private_key}")
    try:
        public_value = public_key.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProxmoxBootstrapError("Unable to read the Proxmox bootstrap public key") from exc
    if not public_value.startswith("ssh-ed25519 ") or "\n" in public_value:
        raise ProxmoxBootstrapError("The Proxmox bootstrap public key is invalid")
    return private_key, public_value, created


def build_plan(
    config: HomelabConfig,
    *,
    ssh_target: str | None = None,
    role_id: str = DEFAULT_ROLE_ID,
    rotate_token: bool = False,
) -> BootstrapPlan:
    match = TOKEN_ID_PATTERN.fullmatch(config.proxmox.token_id)
    if not match:
        raise ProxmoxBootstrapError(
            "proxmox.token_id must use user@realm!token format before bootstrap"
        )
    if not ROLE_ID_PATTERN.fullmatch(role_id):
        raise ProxmoxBootstrapError(
            "Role ID must start with a letter and contain only letters/numbers"
        )
    host = config.proxmox.api_url.host
    target = ssh_target or f"root@{host}"
    if not SSH_TARGET_PATTERN.fullmatch(target):
        raise ProxmoxBootstrapError("SSH target must use user@host format")
    return BootstrapPlan(
        ssh_target=target,
        user_id=f"{match.group('user')}@{match.group('realm')}",
        role_id=role_id,
        token_name=match.group("token"),
        token_id=config.proxmox.token_id,
        privileges=PROVISIONING_PRIVILEGES,
        rotate_token=rotate_token,
    )


def apply_bootstrap(
    config: HomelabConfig,
    secrets_path: str | Path | None,
    *,
    ssh_target: str | None = None,
    role_id: str = DEFAULT_ROLE_ID,
    rotate_token: bool = False,
    ssh_executable: str | None = None,
    ssh_private_key: str | Path | None = None,
    sops_executable: str | None = None,
    diagnostic_log_path: str | Path | None = None,
) -> BootstrapResult:
    plan = build_plan(config, ssh_target=ssh_target, role_id=role_id, rotate_token=rotate_token)
    diagnostic = DiagnosticLog(diagnostic_log_path)
    diagnostic.write(
        "bootstrap.start",
        f"target={plan.ssh_target} user={plan.user_id} role={plan.role_id} "
        f"token={plan.token_id} rotate={rotate_token}",
    )
    ssh = ssh_executable or shutil.which("ssh")
    if not ssh:
        raise ProxmoxBootstrapError(
            "OpenSSH client is not installed or is not on PATH", diagnostic_log=diagnostic.path
        )
    command = [
        ssh,
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if ssh_private_key is not None:
        command.extend(["-i", str(resolve_bootstrap_ssh_key(ssh_private_key))])
    command.extend(
        [
            plan.ssh_target,
            "bash",
            "-s",
            "--",
            plan.user_id,
            plan.role_id,
            plan.token_name,
            "1" if rotate_token else "0",
            ",".join(plan.privileges),
        ]
    )
    try:
        diagnostic.write("ssh.execute", f"executable={ssh} target={plan.ssh_target}")
        completed = subprocess.run(
            command,
            input=REMOTE_BOOTSTRAP_SCRIPT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        diagnostic.write("ssh.exception", f"{type(exc).__name__}: {exc}")
        raise ProxmoxBootstrapError(
            "Unable to run the Proxmox bootstrap over SSH", diagnostic_log=diagnostic.path
        ) from exc
    diagnostic.write("ssh.result", f"exit_code={completed.returncode}")
    for line in safe_remote_diagnostics(completed.stderr, limit=None):
        diagnostic.write("ssh.stderr", line)
    if completed.returncode != 0:
        diagnostics = safe_remote_diagnostics(completed.stderr)
        detail = (
            "\nRemote diagnostics:\n" + "\n".join(diagnostics)
            if diagnostics
            else "\nNo safe remote diagnostics were returned."
        )
        raise ProxmoxBootstrapError(
            "Proxmox bootstrap failed while running pveum over administrator SSH." + detail,
            diagnostic_log=diagnostic.path,
        )
    try:
        response = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        diagnostic.write("ssh.stdout", "invalid protected JSON response (content suppressed)")
        raise ProxmoxBootstrapError(
            "Proxmox bootstrap returned an invalid protected response",
            diagnostic_log=diagnostic.path,
        ) from exc

    diagnostic.write(
        "ssh.stdout",
        "existing-token response"
        if response.get("status") == "existing"
        else "new-token response (value suppressed)",
    )

    if response.get("status") == "existing":
        try:
            bundle = load_secrets(secrets_path, config=config, sops_executable=sops_executable)
        except SecretPlaceholderError as exc:
            raise ProxmoxTokenRecoveryRequired(
                "The Proxmox token exists, but SOPS still contains its generated placeholder.",
                diagnostic_log=diagnostic.path,
            ) from exc
        except SecretError as exc:
            raise ProxmoxBootstrapError(
                "The token exists, but the encrypted secret store could not be read safely. "
                "Repair SOPS/age access before attempting token recovery.",
                diagnostic_log=diagnostic.path,
            ) from exc
        api_token = bundle.proxmox.api_token.get_secret_value()
        if not api_token.startswith(f"{plan.token_id}="):
            raise ProxmoxTokenRecoveryRequired(
                "The existing Proxmox token does not match the credential stored in SOPS.",
                diagnostic_log=diagnostic.path,
            )
        diagnostic.write("sops.read", "existing Proxmox token loaded")
        verify_api_token(config, api_token, diagnostic=diagnostic)
        diagnostic.write("bootstrap.complete", "existing identity reconciled and verified")
        return BootstrapResult(False, plan.token_id, plan.role_id, diagnostic.path)

    token_value = response.get("value")
    if not isinstance(token_value, str) or not token_value:
        raise ProxmoxBootstrapError(
            "Proxmox did not return the one-time API token value", diagnostic_log=diagnostic.path
        )
    api_token = f"{plan.token_id}={token_value}"
    try:
        set_proxmox_token(secrets_path, api_token, sops_executable=sops_executable)
    except SecretError as exc:
        diagnostic.write("sops.write", f"failed: {type(exc).__name__}: {exc}")
        raise ProxmoxBootstrapError(
            "The token was created, but its secret could not be saved to SOPS. "
            "Rotate the token after repairing the encrypted secret workflow.",
            diagnostic_log=diagnostic.path,
        ) from exc
    diagnostic.write("sops.write", "new Proxmox token stored")
    verify_api_token(config, api_token, diagnostic=diagnostic)
    diagnostic.write("bootstrap.complete", "identity created or rotated and verified")
    return BootstrapResult(True, plan.token_id, plan.role_id, diagnostic.path)


def verify_api_token(
    config: HomelabConfig, api_token: str, *, diagnostic: DiagnosticLog | None = None
) -> None:
    endpoint = str(config.proxmox.api_url).rstrip("/") + "/api2/json/version"
    request = urllib.request.Request(
        endpoint,
        headers={"Authorization": f"PVEAPIToken={api_token}"},
        method="GET",
    )
    context = ssl.create_default_context()
    if not config.proxmox.verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if diagnostic is not None:
        diagnostic.write(
            "api.request", f"method=GET endpoint={endpoint} verify_tls={config.proxmox.verify_tls}"
        )
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            if diagnostic is not None:
                diagnostic.write(
                    "api.response",
                    f"status={response.status} reason={getattr(response, 'reason', '')}",
                )
            if response.status != 200:
                raise ProxmoxBootstrapError(
                    "Proxmox API token verification did not succeed",
                    diagnostic_log=diagnostic.path if diagnostic else None,
                )
    except urllib.error.HTTPError as exc:
        body = ""
        with suppress(OSError, AttributeError):
            body = exc.read(4096).decode("utf-8", errors="replace")
        if diagnostic is not None:
            diagnostic.write("api.http_error", f"status={exc.code} reason={exc.reason} body={body}")
        raise ProxmoxBootstrapError(
            f"Proxmox API token verification failed with HTTP {exc.code} ({exc.reason}).",
            diagnostic_log=diagnostic.path if diagnostic else None,
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        if diagnostic is not None:
            diagnostic.write("api.exception", f"{type(exc).__name__}: {exc}")
        raise ProxmoxBootstrapError(
            "Proxmox API token verification failed. Check TLS trust, endpoint, and role permissions.",
            diagnostic_log=diagnostic.path if diagnostic else None,
        ) from exc
