# Controlplane Platform

Provision a production Ubuntu controlplane on Proxmox VE and a closely matched
Ubuntu WSL 2 environment for development and testing. Every installation is
pinned to a published release and verified with SHA-256 before execution.

![Release](https://img.shields.io/badge/release-v0.1.1--test.4-blue?style=for-the-badge)
![Channel](https://img.shields.io/badge/channel-test-orange?style=for-the-badge)
![Released](https://img.shields.io/badge/released-2026--08--22-informational?style=for-the-badge)
![Checksums](https://img.shields.io/badge/checksums-SHA--256-blue?style=for-the-badge)

| Current release | Published | Channel |
| --- | --- | --- |
| `v0.1.1-test.4` | `2026-08-22` | `test` |

> [!WARNING]
> Test releases require validation before production use.

## What this project provides

| Platform | Intended use | Environment |
| --- | --- | --- |
| Proxmox VE | Production | Unprivileged Ubuntu LXC |
| Windows 11 WSL 2 | Development and testing | Ubuntu WSL distribution |

Both installers provide an interactive Ubuntu 24.04 LTS or Ubuntu 26.04 LTS
setup and apply the shared Controlplane baseline as closely as each platform
allows.

## Install the current release

The following commands are already pinned to `v0.1.1-test.4`. Copy the command
for your platform without replacing any values.

### Proxmox VE

Run in the Proxmox VE host shell as `root`:

```bash
curl -fsSL https://raw.githubusercontent.com/Fouchger/Homelab/test/install-proxmox.sh | bash -s -- --release v0.1.1-test.4
```

### Windows WSL

Run in Windows PowerShell. The installer requests elevation only when Windows
requires it:

```powershell
& ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/Fouchger/Homelab/test/install-wsl.ps1'))) -Release 'v0.1.1-test.4'
```

## Security and verification

Both bootstrap installers download the matching SHA-256 checksum from the
GitHub release and verify the runtime asset before executing it.

On Windows, the bootstrap asks for approval before starting a separate
PowerShell process with a temporary execution-policy bypass. The bypass ends
when that process exits and does not change the user or machine policy. A
`Restricted` or `AllSigned` Group Policy cannot be overridden by elevation; a
Windows administrator must change the managed policy or provide signed scripts.

## Releases and support information

- [Release history](RELEASES.md) — newest version first
- [Current release notes](releases/v0.1.1-test.4.md)
- [Machine-readable release index](releases/index.json)
- [Third-party notices](NOTICE.md)

## Public repository scope

This branch contains only the files required to install and verify public
runtime releases. Development source, tests, build tools and private repository
history are not published here.
