# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added

- SOPS/age encrypted runtime-secret initialization, editing, validation, and readiness checks.
- Strict in-memory Proxmox and Cloudflare credential loading with plaintext-file refusal and
  redaction-safe failures.
- Age identity backup, recovery, recipient rotation, and provider-token rotation guidance.
- Installer support for age and checksum-verified SOPS binaries.
- Planned, idempotent Proxmox API role/user/ACL/token bootstrap with separated-token permissions,
  explicit rotation, direct SOPS capture, and authenticated API verification.

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
