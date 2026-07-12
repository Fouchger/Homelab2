# Development roadmap

This document records release boundaries and sequencing. GitHub issues hold the detailed scope,
acceptance criteria, and implementation discussion for each active workstream.

## Release status

| Release | Focus | Status |
|---|---|---|
| `v0.1.0` | Phase 1: control-plane foundation | Complete |
| `v0.2.0` | Phase 2: secure provisioning foundation | In progress |
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

## Outstanding work

| Priority | Workstream | Tracking | Depends on |
|---|---|---|---|
| 1 | CLI and clean-installer acceptance coverage | [#3](https://github.com/Fouchger/Homelab2/issues/3) | Phase 1 |
| 2 | SOPS and age secret management | [#4](https://github.com/Fouchger/Homelab2/issues/4) | Phase 1 |
| 3 | Proxmox API identity bootstrap | [#10](https://github.com/Fouchger/Homelab2/issues/10) | #4 |
| 4 | OpenTofu project and state strategy | [#5](https://github.com/Fouchger/Homelab2/issues/5) | #4 |
| 5 | Proxmox resource provisioning | [#6](https://github.com/Fouchger/Homelab2/issues/6) | #4, #5, #10 |
| 6 | Multi-domain Cloudflare DNS provisioning | [#7](https://github.com/Fouchger/Homelab2/issues/7) | #4, #5 |
| 7 | Ansible inventory and baseline configuration | [#8](https://github.com/Fouchger/Homelab2/issues/8) | #6 |
| 8 | Guarded plan and apply operations | [#9](https://github.com/Fouchger/Homelab2/issues/9) | #5, #6, #7, #8 |

Issues #4, #10, and #5 form the Phase 2 security, API identity, and infrastructure foundation.
Proxmox and Cloudflare can then progress independently. Ansible follows usable Proxmox outputs,
and control-panel apply operations come last so the interface exposes only workflows that are
already safe and tested.

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
