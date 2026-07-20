"""Pinned Proxmox Community Scripts provisioning for the replacement DNS LXC."""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from homelabctl.configuration import find_project_root, load_config
from homelabctl.guard import OperationLockedError, mutation_lock
from homelabctl.models import HomelabConfig, ProxmoxLxcSettings
from homelabctl.proxmox_bootstrap import (
    DiagnosticLog,
    resolve_bootstrap_ssh_key,
    safe_remote_diagnostics,
)
from homelabctl.tofu import TofuError, resolved_ssh_public_keys

COMMUNITY_SCRIPTS_REVISION = "1cfddc4c9c28243c455a20fab3ef5d423ffc9d80"
TECHNITIUM_ENTRY_SHA256 = "56e839cf340f5b7a99c4967b8dbbd9231187a9c72c1e5d8408f145c30ddc2b08"
BUILD_FUNC_SHA256 = "40b85ff7dd7705b5464d012c4c79596ae689af695d99a27bfe07303641ad1f8a"
TECHNITIUM_VERSION = "15.4.0"


class DnsProvisionError(RuntimeError):
    """Raised when the DNS helper deployment is ambiguous or fails safely."""


@dataclass(frozen=True, slots=True)
class DnsProvisionPlan:
    guest: ProxmoxLxcSettings
    revision: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DnsProvisionResult:
    created: bool
    guest: str
    address: str
    diagnostic_log: Path


def _dns_guest(config: HomelabConfig) -> ProxmoxLxcSettings:
    applications = [
        app for app in config.applications.values() if app.enabled and app.type == "technitium"
    ]
    if len(applications) != 1:
        raise DnsProvisionError("Exactly one enabled Technitium application is required")
    matches = [guest for guest in config.proxmox.containers if guest.key == applications[0].guest]
    if len(matches) != 1:
        raise DnsProvisionError("The Technitium application guest is not declared exactly once")
    guest = matches[0]
    if guest.provisioner != "community-script" or guest.helper_script != "technitiumdns":
        raise DnsProvisionError(
            "The Technitium guest must use provisioner=community-script and helper_script=technitiumdns"
        )
    if guest.nesting or not guest.protection or not guest.started or not guest.start_on_boot:
        raise DnsProvisionError(
            "The DNS helper guest must be protected, started, on-boot, and have nesting disabled"
        )
    return guest


def dns_provision_plan(config_path: Path) -> DnsProvisionPlan:
    config = load_config(config_path)
    guest = _dns_guest(config)
    lines = (
        f"Create or verify {guest.hostname} as Proxmox LXC VMID {guest.vm_id}",
        f"Static address: {guest.address}; gateway: {config.network.gateway}; VLAN: {config.network.vlan_id}",
        f"Resources: {guest.cores} vCPU, {guest.memory_mb} MiB RAM, {guest.disk_gb} GiB disk",
        "Owner: Proxmox Community Scripts (not OpenTofu)",
        f"Pinned upstream revision: {COMMUNITY_SCRIPTS_REVISION}",
        f"Entry SHA-256: {TECHNITIUM_ENTRY_SHA256}",
        f"Build helper SHA-256: {BUILD_FUNC_SHA256}",
        f"Required Technitium version after installation: {TECHNITIUM_VERSION}",
        "All transitive helper downloads are rewritten to the same immutable revision",
        "Existing VMIDs are verified and never overwritten or recreated",
    )
    return DnsProvisionPlan(guest, COMMUNITY_SCRIPTS_REVISION, lines)


REMOTE_DNS_PROVISION_SCRIPT = r"""#!/usr/bin/env bash
set -Eeuo pipefail
vmid="$1"; hostname="$2"; address="$3"; gateway="$4"; bridge="$5"; vlan="$6"
cores="$7"; memory="$8"; disk="$9"; storage="${10}"; nameservers="${11}"
public_key_b64="${12}"; revision="${13}"; entry_sha="${14}"; build_sha="${15}"
technitium_version="${16}"
exec 2> >(sed 's/^/HOMELAB_DNS: /' >&2)
info() { printf '==> %s\n' "$*" >&2; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail "root access is required"
command -v pct >/dev/null || fail "pct is unavailable"
[[ "$vmid" =~ ^[0-9]+$ ]] || fail "invalid VMID"
[[ "$vlan" =~ ^[0-9]+$ ]] || fail "invalid VLAN"
public_key="$(printf '%s' "$public_key_b64" | base64 -d)"
[[ "$public_key" == ssh-ed25519\ * ]] || fail "invalid automation public key"

verify_existing() {
  local config
  config="$(pct config "$vmid")"
  grep -Fqx "hostname: $hostname" <<<"$config" || fail "VMID $vmid belongs to another hostname"
  grep -F "ip=$address" <<<"$config" >/dev/null || fail "VMID $vmid has a different address"
  grep -F "tag=$vlan" <<<"$config" >/dev/null || fail "VMID $vmid has a different VLAN"
  pct status "$vmid" | grep -q 'status: running' || pct start "$vmid"
  pct exec "$vmid" -- systemctl is-active --quiet technitium || fail "Technitium is not active"
  installed_version="$(pct exec "$vmid" -- cat /root/.technitium 2>/dev/null || true)"
  [ "$installed_version" = "$technitium_version" ] || fail "Technitium version is $installed_version; required $technitium_version"
}

if pct status "$vmid" >/dev/null 2>&1; then
  info "Verifying existing DNS LXC $vmid"
  verify_existing
  printf 'HOMELAB_DNS_RESULT=existing\n'
  exit 0
fi

work="$(mktemp -d /tmp/homelab-dns-helper.XXXXXX)"
trap 'rm -rf -- "$work"' EXIT
base="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/$revision"
curl -fsSL "$base/ct/technitiumdns.sh" -o "$work/technitiumdns.sh"
curl -fsSL "$base/misc/build.func" -o "$work/build.func"
printf '%s  %s\n' "$entry_sha" "$work/technitiumdns.sh" | sha256sum -c -
printf '%s  %s\n' "$build_sha" "$work/build.func" | sha256sum -c -
sed -i "s#https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/#$base/#g" "$work/build.func"
sed -i "2c source $work/build.func" "$work/technitiumdns.sh"
info "Running pinned Community Scripts revision $revision"
PHS_SILENT=1 DIAGNOSTICS=no mode=default \
var_ctid="$vmid" var_hostname="$hostname" var_cpu="$cores" var_ram="$memory" \
var_disk="$disk" var_os=debian var_version=13 var_unprivileged=1 \
var_brg="$bridge" var_vlan="$vlan" var_net="$address" var_gateway="$gateway" \
var_ns="$nameservers" var_container_storage="$storage" var_protection=1 \
var_nesting=0 var_ssh=yes var_ssh_authorized_key="$public_key" \
bash "$work/technitiumdns.sh" default >"/var/log/homelab-dns-helper-$vmid.log" 2>&1
pct set "$vmid" --onboot 1 --protection 1 --tags 'community-script;dns;homelab;network-core' >/dev/null
verify_existing
printf 'HOMELAB_DNS_RESULT=created\n'
"""


def provision_dns_lxc(
    config_path: Path,
    *,
    ssh_executable: str | None = None,
    ssh_private_key: str | Path | None = None,
) -> DnsProvisionResult:
    config = load_config(config_path)
    plan = dns_provision_plan(config_path)
    try:
        public_keys = resolved_ssh_public_keys(config)
    except TofuError as exc:
        raise DnsProvisionError(str(exc)) from exc
    if len(public_keys) != 1:
        raise DnsProvisionError("DNS provisioning requires exactly one automation SSH public key")
    ssh = ssh_executable or shutil.which("ssh")
    if not ssh:
        raise DnsProvisionError("OpenSSH client is not installed or not on PATH")
    target = f"root@{config.proxmox.api_url.host}"
    diagnostic = DiagnosticLog(find_project_root(config_path.parent) / "logs" / "dns-provision.log")
    nameservers = ",".join(str(item) for item in config.network.dns_servers)
    args = [
        str(plan.guest.vm_id),
        plan.guest.hostname,
        str(plan.guest.address),
        str(config.network.gateway),
        config.network.bridge,
        str(config.network.vlan_id),
        str(plan.guest.cores),
        str(plan.guest.memory_mb),
        str(plan.guest.disk_gb),
        config.proxmox.storage,
        nameservers,
        base64.b64encode(public_keys[0].encode()).decode(),
        plan.revision,
        TECHNITIUM_ENTRY_SHA256,
        BUILD_FUNC_SHA256,
        TECHNITIUM_VERSION,
    ]
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
    command.extend([target, "bash", "-s", "--", *args])
    diagnostic.write(
        "dns.provision.start", f"target={target} vmid={plan.guest.vm_id} revision={plan.revision}"
    )
    try:
        with mutation_lock(find_project_root(config_path.parent), "Provision replacement DNS LXC"):
            completed = subprocess.run(
                command,
                input=REMOTE_DNS_PROVISION_SCRIPT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=1800,
            )
    except (OSError, subprocess.SubprocessError, OperationLockedError) as exc:
        raise DnsProvisionError(f"Unable to provision DNS LXC: {exc}") from exc
    for line in safe_remote_diagnostics(
        completed.stderr.replace("HOMELAB_DNS:", "HOMELAB_BOOTSTRAP:"), limit=None
    ):
        diagnostic.write("dns.ssh", line.replace("HOMELAB_BOOTSTRAP:", "HOMELAB_DNS:"))
    if completed.returncode != 0:
        raise DnsProvisionError(f"DNS helper provisioning failed; review {diagnostic.path}")
    match = re.fullmatch(r"HOMELAB_DNS_RESULT=(created|existing)\s*", completed.stdout)
    if not match:
        raise DnsProvisionError(
            f"DNS helper returned an invalid response; review {diagnostic.path}"
        )
    created = match.group(1) == "created"
    diagnostic.write("dns.provision.complete", "created" if created else "verified existing")
    return DnsProvisionResult(
        created, plan.guest.hostname, str(plan.guest.address.ip), diagnostic.path
    )
