# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- Complete whole-homelab future-state scope covering MikroTik, Proxmox, Technitium, OpenMediaVault,
  a Deployrr-compatible Traefik/DockFlare edge stack, one managed Plex service, Immich, backup,
  exposure, capacity, and recovery boundaries.
- Grouped VMIDs beginning at 200, static host addresses below 100, DHCP host addresses above 200,
  and Ubuntu 24.04 as the default operating system for new managed guests.
- Phase 6 execution and development plan with ordered workstreams, acceptance gates, a GitHub
  progress workflow, and a reusable workstream issue template.
- Community Scripts as a pinned, checksum-verified VM/LXC bootstrap accelerator beneath Homelab2's
  unattended orchestration and no-destroy safety boundary.
- A versioned whole-site manifest and generated JSON Schema covering networks, guests,
  applications, exposure, backup, ownership, stable credential references, and capacity.
- A provider-independent safety engine that refuses destructive discovered-resource plans,
  VMID/address collisions, unsafe capacity pressure, incomplete immutable identifiers, and
  secret-bearing evidence before provider execution.

## [0.4.0] - 2026-07-17

### Added

- OpenTofu-derived, ignored Ansible runtime inventory with configuration/state drift refusal.
- A guarded Setup-menu and CLI workflow that installs `ansible-core` and locked collections on
  existing Debian/Ubuntu control planes using root or sudo, with serialized execution and logs.
- A consistent live progress banner, elapsed-time display, 15-second activity heartbeat, and
  operation-button lock for every control-panel action.
- Responsive multi-row action grids with an explicit scroll hint, ensuring sections with more than
  three operations no longer clip later menu actions.
- Explicit per-section menu sequence metadata, visible numbered steps, and workflow guidance so
  users can follow prerequisite actions in the intended order.
- Compact two-pane purpose pages that keep ordered actions on the left and live session activity
  visible on the right, reducing vertical scroll on standard terminal sizes.
- Locked Debian-family guest baseline covering hostname, timezone, prerequisite packages, the
  dedicated automation account, authorized key, explicit sudo policy, and an ownership marker.
- CLI, Task, and Infrastructure-menu operations for inventory preview, baseline check mode, and a
  plan/confirm/apply baseline workflow with sanitized diagnostics.
- Provenance-checked OpenTofu plans, a cross-process infrastructure mutation lock, and a guarded
  OpenTofu apply option in the Infrastructure menu.
- A curated Uptime Kuma 2.4.0 pilot using checksum-verified immutable source and frontend
  artifacts, versioned application code, persistent data separation, dedicated-account execution,
  health checks, and documented update, rollback, and rebuild procedures.

### Fixed

- Menu-launched Ansible operations stream real output, avoid hidden first-connection prompts, and
  stop bounded baseline or application operations with actionable diagnostics.
- Debian package acquisition uses bounded connection, lock, and cache-refresh limits.
- Uptime Kuma preview no longer attempts stateful extraction, the adapter avoids the Ansible ACL
  transition issue, and unnecessary Chromium installation was removed.

### Verified

- Production acceptance of inventory, baseline, guarded applies, Uptime Kuma install, idempotent
  application re-apply, service restart, health checks, alert notifications, and Proxmox HTTPS
  monitoring across the intentionally narrow VLAN firewall path.
- Formatting, linting, and 101 automated tests.

## [0.3.0] - 2026-07-16

### Added

- Strict site models for stable-key, unprivileged Debian LXC guests with static management
  addressing, sizing, template, lifecycle, tags, and public-key bootstrap settings.
- Dedicated automation public-key file references with validated in-memory loading for OpenTofu.
- Guarded Infrastructure menu and CLI actions that create, verify, fingerprint, permission, and
  configure the dedicated guest automation SSH identity without exposing private material.
- Strict multi-zone Cloudflare A, AAAA, and CNAME records with exact ownership identities,
  public-target validation, safe TTL/proxy defaults, and internal-domain leakage prevention.
- Deterministic OpenTofu Proxmox container and Cloudflare DNS resources with structured,
  secret-free outputs for later Ansible inventory.
- Exact Cloudflare provider pinning and a regenerated multi-platform provider lockfile.
- Phase 3 provisioning and DNS ownership operator guides.
- Credential-aware CLI and Task application of only the existing reviewed OpenTofu saved plan.

### Changed

- The OpenTofu runner now passes only in-memory provider credentials, requires the Cloudflare token
  when records are declared, and redacts both provider tokens from diagnostics.
- The guided configuration form preserves Phase 3 resources that are currently edited in YAML.
- Debian 13 LXC guidance records the systemd 257 nesting requirement and its isolation tradeoff.

### Fixed

- Cloudflare saved-plan applies now receive the SOPS-decrypted API token in memory instead of
  failing after any independent Proxmox changes have already completed.

### Verified

- OpenTofu formatting, provider initialization, schema validation, empty example planning, and an
  offline one-container creation plan.
- Generated JSON Schema, example configuration validation, focused model/secret/OpenTofu/UI tests,
  and Ruff checks.
- Saved-plan application with both runtime provider credentials, exact-plan enforcement, missing
  plan refusal, diagnostic redaction, and partial-apply recovery guidance.
- Live disposable Proxmox acceptance covering create, no-change reconciliation, in-place update,
  stable reordering, replacement, VLAN 30 connectivity from the VLAN 20 control plane, healthy
  Debian 13 startup, reviewed destroy, and verified removal.
- Live two-zone Cloudflare acceptance covering create, authoritative lookup, in-place TTL update,
  stable reordering, reviewed deletion, authoritative NXDOMAIN, and clean final reconciliation.

## [0.2.0] - 2026-07-13

### Added

- SOPS/age encrypted runtime-secret initialization, editing, validation, and readiness checks.
- Strict in-memory Proxmox and Cloudflare credential loading with plaintext-file refusal and
  redaction-safe failures.
- Age identity backup, recovery, recipient rotation, and provider-token rotation guidance.
- Installer support for age and checksum-verified SOPS binaries.
- Planned, idempotent Proxmox API role/user/ACL/token bootstrap with separated-token permissions,
  explicit rotation, direct SOPS capture, and authenticated API verification.
- Control-panel SSH authorization dialog with automatic interactive `ssh-copy-id`, terminal
  clipboard buttons, and a Proxmox-console fallback.
- Proxmox-side privilege argument conversion plus redacted remote SSH/`pveum` diagnostics for
  bootstrap failures.
- JSON-based Proxmox role, user, and token discovery so bootstrap reruns reconcile existing
  identities instead of attempting duplicate creation.
- Guarded menu recovery when a Proxmox token exists but its one-time value is absent from SOPS;
  rotation requires a second confirmation and leaves the user and role intact.
- Persistent, Git-ignored Proxmox bootstrap diagnostics with sanitized SSH/`pveum` output and API
  verification status, reason, and error details.
- Version-constrained OpenTofu foundation with locked Proxmox provider, typed site inputs, a menu
  validation/plan operation, CI checks, and documented local and locked remote-state strategies.
- Guided masked Cloudflare-token capture through SOPS, required-credential readiness enforcement,
  and a responsive/scrollable operations grid that keeps every implemented action reachable.
- Guarded control-plane updates from the Maintenance menu with a changed-file preview,
  fast-forward-only Git protection, locked dependency synchronization, and runtime-file
  preservation; installer updates now ignore untracked runtime artifacts and identify tracked
  source changes precisely.
- Purpose-based Setup, Proxmox, Infrastructure, Maintenance, and Diagnostics menu sections with
  shared session activity, a native terminal selection view, optional direct clipboard transfer,
  and an exported plain-text report for support.
- Independent provider-credential validation so an unfinished Proxmox placeholder does not block
  guided Cloudflare token setup.

### Fixed

- Restored reusable secure TLS and generic management-network defaults after site-specific values
  were accidentally committed to the application model.
- Isolated OpenTofu binary extraction in CI so additional release-archive files cannot overwrite or
  prompt on repository files.

### Verified

- Production site configuration and SOPS/age credentials for Proxmox and two Cloudflare domains.
- Idempotent Proxmox user, role, ACL, and separated API-token reconciliation over administrator
  SSH, followed by successful token authentication to the Proxmox API.
- OpenTofu formatting, locked provider initialization, validation, and non-destructive planning.
- Guarded control-plane update reporting the GitHub version current.
- Formatting, linting, example configuration validation, and the complete automated test suite.

## [0.1.0] - 2026-07-12

### Added

- Interactive terminal control panel with overview, configuration, operations, and help views.
- Strict, versioned YAML configuration with normalization, validation, and atomic saves.
- Internal site domain and optional multi-domain Cloudflare configuration.
- Readiness checks for the required and planned control-plane tools.
- Secret-free YAML and JSON effective-settings output.
- Unattended commands for initialization, validation, inspection, readiness, and schema generation.
- Debian and Ubuntu installer for Git, Task, uv, and repository setup.
- Locked Python dependencies, automated tests, GitHub Actions quality checks, and Dependabot.
- Confirmation-dialog and structured-operation foundations for future infrastructure changes.

### Verified

- Fresh Ubuntu 24.04 Proxmox LXC installation and first-run workflow.
- Configuration validation and effective-settings output with two Cloudflare domains.
- Formatting, linting, example configuration validation, and 14 automated tests on Linux.

[0.1.0]: https://github.com/Fouchger/Homelab2/releases/tag/v0.1.0
[0.2.0]: https://github.com/Fouchger/Homelab2/releases/tag/v0.2.0
[0.3.0]: https://github.com/Fouchger/Homelab2/releases/tag/v0.3.0
[0.4.0]: https://github.com/Fouchger/Homelab2/releases/tag/v0.4.0
