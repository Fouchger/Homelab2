# Development roadmap

This document records release boundaries and sequencing. GitHub issues hold the detailed scope,
acceptance criteria, and implementation discussion for each active workstream.

## Release status

| Release | Focus | Status |
|---|---|---|
| `v0.1.0` | Phase 1: control-plane foundation | Complete |
| `v0.2.0` | Phase 2: secure provisioning foundation | Complete |
| `v0.3.0` | Phase 3: Proxmox and Cloudflare provisioning | Planned |
| `v0.4.0` | Phase 4: system configuration and guarded operations | Planned |

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

## Outstanding work

| Priority | Workstream | Tracking | Depends on |
|---|---|---|---|
| 1 | CLI and clean-installer acceptance coverage | [#3](https://github.com/Fouchger/Homelab2/issues/3) | Phase 1 |
| 2 | Offline age identity backup and recovery verification | [#11](https://github.com/Fouchger/Homelab2/issues/11) | Phase 2 operations |
| 3 | Trusted Proxmox API TLS and certificate verification | [#12](https://github.com/Fouchger/Homelab2/issues/12) | Phase 2 hardening |
| 4 | Proxmox resource provisioning | [#6](https://github.com/Fouchger/Homelab2/issues/6) | Phase 2 |
| 5 | Multi-domain Cloudflare DNS provisioning | [#7](https://github.com/Fouchger/Homelab2/issues/7) | Phase 2 |
| 6 | Ansible inventory and baseline configuration | [#8](https://github.com/Fouchger/Homelab2/issues/8) | #6 |
| 7 | Guarded plan and apply operations | [#9](https://github.com/Fouchger/Homelab2/issues/9) | #6, #7, #8 |

Issues #6 and #7 are the Phase 3 provisioning workstreams and can progress independently on the
completed Phase 2 foundation. Ansible follows usable Proxmox outputs, and control-panel apply
operations come last so the interface exposes only workflows that are already safe and tested.
Issues #11 and #12 preserve the explicit operator backup and TLS-hardening work without reopening
the completed software foundation.

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
