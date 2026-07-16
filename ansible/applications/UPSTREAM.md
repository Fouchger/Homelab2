# Curated Uptime Kuma snapshot

Homelab2's adapter was reviewed against Community Scripts' Uptime Kuma installer at commit
`b9f26d66ed5131bcded155ebb83784f303cf4355`:

- source: `install/uptimekuma-install.sh`
- upstream blob: `69d04a763c4fc46506415c9de9c9c6e49776947d`
- upstream project: <https://github.com/community-scripts/ProxmoxVE>
- copyright: 2021-2026 tteck / Community Scripts contributors
- license: MIT; see `COMMUNITY-SCRIPTS-LICENSE.txt`

The upstream installer depends on runtime helper injection and downloads an application frontend
without verifying its checksum. Homelab2 therefore does not execute that script. The reviewed
workflow is reimplemented as a non-interactive Ansible adapter with these immutable inputs:

| Input | Immutable reference | SHA-256 |
|---|---|---|
| Uptime Kuma source | tag `2.4.0` | `0ad39c4cbe2de5a2dd4869d02a8a4f0398b7b16217b0aeaff98d78cf37500c42` |
| Uptime Kuma frontend | release `2.4.0/dist.tar.gz` | `015ebb4df74b72bd8c303bdc41b71e2de8bdc72862ddc2d65db69a92316df835` |

Updating requires selecting a new immutable release, downloading both artifacts for review,
recomputing their SHA-256 hashes, updating the adapter and constants together, and repeating
install, idempotence, health, rollback, and disposable rebuild acceptance.
