# Development roadmap

This document records release boundaries and sequencing. GitHub issues hold the detailed scope,
acceptance criteria, and implementation discussion for each active workstream.

## Release status

| Release | Focus | Status |
|---|---|---|
| `v0.1.0` | Phase 1: control-plane foundation | Complete |
| `v0.2.0` | Phase 2: secure provisioning foundation | Complete |
| `v0.3.0` | Phase 3: Proxmox and Cloudflare provisioning | Complete |
| `v0.4.0` | Phase 4: system configuration and guarded operations | Complete |
| `v0.5.0` | Phase 5: whole-homelab architecture and build design | Documentation complete |
| `v0.6.0` | Phase 6: automated whole-homelab build | Planned |

## Phase 5 plan

Phase 5 expands the control-plane boundary from guest provisioning to the complete homelab
bootstrap path. It adopts the existing MikroTik edge, models VLAN, DHCP, Wi-Fi, routing, firewall,
and DNS ownership, and establishes a clean control plane and core DNS foundation on the existing
Proxmox host.

The existing OpenMediaVault VM, two Plex containers, and Immich container are protected legacy
workloads. Phase 5 must document and preserve their raw-disk, media-mount, database, GPU, network,
and startup dependencies but must not place them under destructive lifecycle management. All other
existing guests are replaceable after their dependencies or replacements have been verified.

Homelab2 does not stop, delete, destroy, or replace any discovered server. It builds and validates
replacements alongside existing systems; only the operator may manually retire an old server after
accepting its replacement.

The architecture and staged safety boundary are recorded in
[`docs/HOMELAB_ARCHITECTURE.md`](docs/HOMELAB_ARCHITECTURE.md) and
[`docs/CLEAN_REBUILD_PLAN.md`](docs/CLEAN_REBUILD_PLAN.md).

The complete deployment and application target is recorded in
[`docs/FUTURE_STATE.md`](docs/FUTURE_STATE.md). Phase 6 sequencing, development requirements,
acceptance gates, and GitHub workflow are defined in
[`docs/PHASE_6_EXECUTION_PLAN.md`](docs/PHASE_6_EXECUTION_PLAN.md).

Phase 5 is documentation-only. It does not authorize or perform any production infrastructure
change. Its acceptance boundary is a complete future-state catalogue, explicit tool ownership,
the no-destroy migration contract, resource and exposure guardrails, and an issue-ready Phase 6
execution plan.

## Phase 6 plan

Phase 6 implements the accepted design through GitHub-tracked workstreams. It adds the whole-site
manifest and safety engine, MikroTik desired state, pinned Community Scripts integration, the
replacement control plane and DNS, the Deployrr-compatible edge and media Docker platforms,
OpenMediaVault adoption, consolidation into one Plex service, the Immich side-by-side rebuild, and
full recovery acceptance. New managed guests standardize on Ubuntu 24.04 unless a documented
upstream support or appliance requirement justifies another operating system.

Community Scripts accelerate reviewed VM and LXC creation. Deployrr supplies reviewed Docker and
Traefik conventions. Neither is the desired-state owner: Homelab2 pins inputs, supplies unattended
configuration, validates results, records evidence, and refuses destructive actions against every
discovered server.

## Phase 1 acceptance

Phase 1 was accepted on 2026-07-12 after verification on an Ubuntu 24.04 Proxmox LXC. The release
includes:

- the interactive terminal control panel and unattended CLI;
- strict, versioned site configuration with atomic persistence;
- internal DNS and zero, one, or many external Cloudflare domains;
- readiness checks and secret-free effective-settings output;
- confirmation-dialog infrastructure for future destructive operations;
- a Debian/Ubuntu installer for Git, Task, uv, and the repository;
- locked dependencies, continuous integration, and dependency updates.

The clean control-plane acceptance run passed configuration validation, readiness checks,
formatting, linting, and all 14 automated tests.

## Phase 2 acceptance

Phase 2 was accepted on 2026-07-13 after verification from the Ubuntu control plane against the
Proxmox VE host. The release includes:

- SOPS/age encrypted Proxmox and Cloudflare runtime credentials with masked guided entry;
- documented age identity backup, recovery, recipient rotation, and token rotation workflows;
- an idempotent Proxmox user, role, ACL, and separated API-token bootstrap over administrator SSH;
- explicit recovery when an existing token's one-time value is unavailable;
- authenticated Proxmox API verification and sanitized persistent diagnostics;
- a version-constrained OpenTofu foundation with locked providers and typed site inputs;
- non-destructive formatting, initialization, validation, and saved-plan checks;
- guarded control-plane updates and purpose-based Setup, Proxmox, Infrastructure, Maintenance, and
  Diagnostics menus;
- portable, secret-free session activity export for remote-terminal support.

The acceptance run validated the production site, encrypted credentials for both configured
Cloudflare domains, the reconciled `homelab@pve!control-plane` identity, successful Proxmox API
authentication, the OpenTofu foundation plan, and an up-to-date control plane. Issues #4, #5, and
#10 were closed with their detailed completion evidence.

## Deferred follow-up work

| Priority | Workstream | Tracking | Depends on |
|---|---|---|---|
| 1 | CLI and clean-installer acceptance coverage | [#3](https://github.com/Fouchger/Homelab2/issues/3) | Phase 1 |
| 2 | Offline age identity backup and recovery verification | [#11](https://github.com/Fouchger/Homelab2/issues/11) | Phase 2 operations |
| 3 | Trusted Proxmox API TLS and certificate verification | [#12](https://github.com/Fouchger/Homelab2/issues/12) | Phase 2 hardening |
| 4 | Curated application recovery on a disposable workload | [#15](https://github.com/Fouchger/Homelab2/issues/15) | Phase 4 pilot |

Issues #6 and #7 completed the Phase 3 provisioning workstreams. Issues #8, #9, and #14 completed
the Phase 4 inventory, guarded-operation, and curated application-pilot workstreams. Issues #11
and #12 preserve the explicit operator backup and TLS-hardening work without reopening completed
releases. Issue #15 retains the deliberately deferred disposable recovery acceptance: Community
Scripts remain an upstream reference only and never share ownership of an OpenTofu-managed guest.

## Phase 4 acceptance

Phase 4 was accepted on 2026-07-17 against the production control plane, Proxmox host, and an
OpenTofu-owned Debian 13 monitoring container. The release includes:

- ignored Ansible inventory derived only from accepted OpenTofu outputs, with state-drift refusal;
- a guarded, serial Debian-family baseline that creates the dedicated automation account, SSH
  policy, explicit sudo policy, package-access limits, and useful live diagnostics;
- sequenced control-panel operations with plan, confirmation, activity streaming, mutation locks,
  and matching unattended commands;
- a checksum-pinned Uptime Kuma 2.4.0 adapter with isolated persistent data, dedicated-account
  dependency installation, systemd service management, and a health check; and
- menu-only operation acceptance, including repeat apply, container restart recovery, notification
  testing, and a least-privilege VLAN 30 to VLAN 20 monitoring firewall path for Proxmox HTTPS.

The Uptime Kuma pilot is healthy at the accepted monitoring endpoint and confirms Proxmox HTTPS
with a 200 response. Disposable rebuild, update/rollback, and persistent-data recovery testing are
explicitly deferred to issue #15 rather than being represented as completed production acceptance.

## Phase 3 acceptance

Phase 3 starts with an OpenTofu-owned, unprivileged Debian LXC profile. Each resource has a stable
key, explicit container ID, hostname, template, size, and management address while inheriting the
validated site node, storage, bridge, VLAN, gateway, DNS, internal domain, and timezone. Structured
outputs provide the guest identity and initial SSH target required by the later Ansible inventory.

Cloudflare manages only explicit external `A`, `AAAA`, and `CNAME` records in existing configured
zones. DNS-only and automatic TTL are the safe defaults. Internal `site.domain` names are excluded,
and every record has exactly one owner: a record declared in the site model belongs to OpenTofu;
future DDNS or tunnel workflows must use separate records and may not mutate it implicitly.

The `v0.3.0` control-panel interface remains plan-only. Live changes use the credential-aware CLI
wrapper to apply only an explicitly reviewed saved plan; the guarded control-panel apply workflow
remains in Phase 4 issue #9.

Phase 3 was accepted on 2026-07-16 from the Ubuntu control plane against the production Proxmox and
Cloudflare accounts. Disposable testing proved LXC create, in-place update, stable reordering,
replacement, Debian 13 health, SSH access across the VLAN boundary, reviewed destroy, and clean
reconciliation. Both Cloudflare zones passed create, authoritative resolution, in-place TTL update,
stable reordering, reviewed deletion, authoritative NXDOMAIN verification, and clean final
reconciliation. Issues #6 and #7 contain the detailed evidence.

## Engineering rules

- A plan must be available before an operation can change infrastructure.
- Secrets must come from the encrypted runtime workflow and must never enter general configuration,
  logs, plans committed to Git, or effective-settings output.
- Interactive and unattended commands must share the same underlying operation implementation.
- Configuration changes must remain backward compatible within a schema version.
- Provider and application dependencies must be version constrained and reproducible.
- New operations require focused tests, failure handling, documentation, and readiness checks.

## Definition of done

An issue is complete when its acceptance criteria pass on the supported Ubuntu control plane, its
automated checks run in CI, its operator workflow is documented, and no unfinished operation is
shown in the control panel. A release is complete when all issues assigned to its phase are closed,
the example configuration and generated schema are current, `task check` passes, and the release is
recorded in `CHANGELOG.md`.
