# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- Strict site models for stable-key, unprivileged Debian LXC guests with static management
  addressing, sizing, template, lifecycle, tags, and public-key bootstrap settings.
- Strict multi-zone Cloudflare A, AAAA, and CNAME records with exact ownership identities,
  public-target validation, safe TTL/proxy defaults, and internal-domain leakage prevention.
- Deterministic OpenTofu Proxmox container and Cloudflare DNS resources with structured,
  secret-free outputs for later Ansible inventory.
- Exact Cloudflare provider pinning and a regenerated multi-platform provider lockfile.
- Phase 3 provisioning and DNS ownership operator guides.

### Changed

- The OpenTofu runner now passes only in-memory provider credentials, requires the Cloudflare token
  when records are declared, and redacts both provider tokens from diagnostics.
- The guided configuration form preserves Phase 3 resources that are currently edited in YAML.

### Verified

- OpenTofu formatting, provider initialization, schema validation, empty example planning, and an
  offline one-container creation plan.
- Generated JSON Schema, example configuration validation, focused model/secret/OpenTofu/UI tests,
  and Ruff checks.

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
