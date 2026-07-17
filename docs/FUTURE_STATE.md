# Complete future state

This document is the authoritative target for the single-host homelab. It defines the systems,
applications, ownership boundaries, exposure policy, data placement, and recovery expectations that
Phase 6 will implement. The migration safety rules in
[`CLEAN_REBUILD_PLAN.md`](CLEAN_REBUILD_PLAN.md) remain mandatory throughout the build.

## Outcomes

The finished homelab must be:

- reproducible from the Git repository, encrypted secrets, backups, and working hardware;
- operated through one guarded Homelab2 workflow instead of a collection of undocumented commands;
- segmented at the MikroTik router and denied by default between VLANs;
- capable of rebuilding managed services without rebuilding OpenMediaVault data disks;
- observable, backed up, and tested for recovery; and
- migrated side by side, with no automatic retirement of any discovered server.

## Physical and platform boundary

| System | Role | Management location |
|---|---|---|
| MikroTik hAP ax2 | WAN, VLAN gateways, firewall, NAT, DHCP, Wi-Fi, WireGuard, NTP | VLAN 20 |
| `pve01` | Proxmox VE hypervisor only | `192.168.20.10` |
| Windows laptop | Bootstrap, emergency router access, recovery pack, operator console | VLAN 20 |

Proxmox runs no application directly on the host. There is one hypervisor, so duplicate guests can
protect against an application failure but cannot provide physical-host high availability.

## Network contract

| VLAN | Subnet | Purpose | Default access policy |
|---:|---|---|---|
| 10 | ISP assigned | WAN handoff | Internet edge only |
| 20 | `192.168.20.0/24` | Management | Administrative access to managed systems |
| 30 | `192.168.30.0/24` | Servers | Published service ports only |
| 40 | `192.168.40.0/24` | Trusted users | Internet and approved internal applications |
| 50 | `192.168.50.0/24` | IoT | Internet and explicitly approved controllers |
| 60 | `192.168.60.0/24` | Guests | Internet only |
| 70 | `192.168.70.0/24` | Storage and backup | Approved NFS/SMB/backup flows only |
| 90 | `192.168.90.0/24` | Reserved DMZ | No workload until a reviewed need exists |

MikroTik owns gateways, DHCP leases and options, routing, Wi-Fi, NAT, WireGuard, and the inter-VLAN
firewall. Technitium owns internal forward and reverse DNS. Cloudflare public records have either
OpenTofu ownership or DockFlare ownership, never both.

## Deployment decisions

| System | Deployment | Initial sizing | Purpose |
|---|---|---:|---|
| `control01` | Unprivileged Ubuntu 24.04 LXC | 2 vCPU, 2 GiB RAM, 32 GiB | Homelab2, OpenTofu, Ansible, SOPS/age |
| `dns-a` | Unprivileged Debian LXC | 1 vCPU, 512 MiB, 4-8 GiB | Primary Technitium DNS |
| `dns-b` | Unprivileged Debian LXC | 1 vCPU, 512 MiB, 4-8 GiB | Secondary Technitium DNS |
| `edge01` | Debian or Ubuntu VM with Docker Compose | 2-4 vCPU, 4 GiB, 40-60 GiB | Ingress, authentication, monitoring, dashboard |
| `media01` | Debian or Ubuntu VM with Docker Compose | 6-8 vCPU, 12 GiB, 150 GiB | Plex, Immich, media application runtime, GPU owner |
| `omv01` | Existing full VM | Existing 2 vCPU, 4 GiB, 32 GiB boot | Storage authority and backup destination |

The exact VMIDs, MAC addresses, and unused IP addresses are allocated by the accepted site manifest
after collision checks. Replacement guests use new identities and do not reuse discovered VMIDs.

`edge01` and `media01` are full VMs because Docker receives its own kernel and security boundary.
The single physical GPU is passed to `media01`, where both Plex containers and Immich can share it.
The GPU handover is a separately approved migration checkpoint.

## Required application catalogue

### Control and infrastructure

| Application | Location | Installation owner | Configuration owner |
|---|---|---|---|
| Homelab2 | `control01` | Repository installer | Homelab2 |
| OpenTofu | `control01` | Locked Homelab2 dependency | Homelab2 |
| Ansible | `control01` | Locked Homelab2 dependency | Homelab2 |
| SOPS and age | `control01` | Checksum-pinned installer | Homelab2 |
| Technitium DNS x2 | `dns-a`, `dns-b` | Pinned Community Scripts adapters | Homelab2 DNS adapter |

### Edge Docker stack

| Container | Required purpose |
|---|---|
| Docker socket proxy | Restrict Docker API exposure |
| Traefik | Internal and approved external HTTP routing |
| DockFlare | Cloudflare Tunnel ingress and Access reconciliation |
| `cloudflared` | Outbound-only Cloudflare Tunnel connector |
| Authelia | Lightweight single sign-on and multi-factor authentication |
| Redis/Valkey | Authelia session storage where required by the accepted template |
| CrowdSec and Traefik bouncer | Request analysis and proxy enforcement |
| Uptime Kuma | Availability monitoring and notifications |
| Homepage | Operator service catalogue and dashboard |
| Dozzle | Read-only operational container-log view |

Deployrr's Traefik, security, networking, and application conventions are the preferred template
source. Homelab2 renders and applies the accepted Compose and configuration files so a rebuild does
not require walking through the Deployrr installer again.

### Media Docker stack

| Container | Required purpose | Persistent-data boundary |
|---|---|---|
| `plex01` | First existing Plex service rebuilt into the managed structure | Local Plex database; OMV media read-only where possible |
| `plex02` | Second existing Plex service rebuilt into the managed structure | Local Plex database; OMV media read-only where possible |
| Immich server | Photo and video application | Local application state; OMV photo library if accepted |
| Immich machine learning | Immich search and recognition | Rebuildable model cache |
| PostgreSQL with Immich extensions | Immich database | Local Proxmox SSD only |
| Redis/Valkey | Immich job and cache service | Local application storage |

The two Plex identities remain separate until their accounts, users, libraries, watch state, remote
access, and distinct purpose are documented. Their existing application data is restored into new
containers rather than manually recreating libraries.

Immich uses its official Docker Compose architecture. Its PostgreSQL database never resides on an
NFS or SMB share. The existing Immich LXC remains untouched until a database-and-media restore into
the new stack has passed user-visible validation.

### Storage and backup

OpenMediaVault remains the sole owner of its five passed-through data disks and Btrfs filesystems.
Neither Proxmox nor Homelab2 may initialize, mount, pool, format, or reclaim those disks.

Required protection includes:

- native Proxmox guest backups to an OMV backup share;
- application-consistent PostgreSQL dumps before Immich backups;
- Plex application-data backups separate from the media library;
- encrypted backups of RouterOS configuration and Homelab2 secrets metadata;
- a Windows-laptop or external copy of the minimum recovery pack; and
- a documented restore test for every managed stateful service.

A Proxmox Backup Server guest on this same host is not part of the initial scope because it does not
protect against loss of the physical host. It may be added when independent hardware is available.

## Access and exposure matrix

| Service | Internal access | Remote access | Cloudflare Tunnel |
|---|---|---|---|
| MikroTik, Proxmox, Homelab2 | VLAN 20 | WireGuard | Never |
| Technitium administration | VLAN 20 | WireGuard | Never |
| OMV administration | VLAN 20 or narrow management rule | WireGuard | Never |
| Traefik and DockFlare dashboards | VLAN 20 | WireGuard | Never |
| Homepage and Uptime Kuma | Trusted networks | WireGuard; Access only if approved | Optional with Access |
| Immich | Trusted networks through Traefik | Explicit compatibility and security review | Optional |
| Plex administration | Trusted networks | WireGuard or Plex account workflow | Never through tunnel |
| Plex media streaming | Direct LAN | Plex Remote Access or WireGuard | Never through tunnel |

Cloudflare Tunnel removes the need for inbound router port forwards for selected web applications.
Plex video traffic is excluded. A service is never public merely because Traefik can route to it;
external exposure requires an explicit manifest entry, DockFlare policy, health check, and operator
approval.

## Tool ownership

| Tool | Responsibility |
|---|---|
| Homelab2 | Workflow, policy, secrets, planning, orchestration, evidence, refusal rules |
| OpenTofu | Imported managed guest lifecycle and explicitly owned Cloudflare records |
| Community Scripts | Reviewed and pinned initial VM/LXC bootstrap implementation |
| Ansible | Guest OS hardening, mounts, packages, configuration, and post-install setup |
| Deployrr | Reference templates and conventions for the Docker application platform |
| Docker Compose | Declarative container lifecycle inside `edge01` and `media01` |
| Traefik | Origin routing, TLS, middleware, and internal/external entry points |
| DockFlare | Cloudflare Tunnel ingress and Access applications/policies |
| MikroTik workflow | RouterOS configuration and validation |
| OpenMediaVault | Raw disks, filesystems, shares, and storage health |

Community Scripts are never executed from a moving branch during a managed build. Each adapter
records the upstream commit, path, checksum, expected inputs, and validation contract. Deployrr
output is imported into reviewed Homelab2 templates; interactive menu automation is not a build
dependency.

A guest created by Community Scripts enters a controlled adoption transaction: Homelab2 reserves
and collision-checks its identity, creates it from pinned inputs, captures its complete Proxmox
configuration, imports it into the matching OpenTofu resource, and requires a zero-change plan.
OpenTofu becomes lifecycle owner only after that acceptance succeeds. A failed or partially adopted
guest is quarantined and reported; Homelab2 does not delete it automatically.

## Capacity guardrail

The target allocations consume approximately 23-25 GiB before temporary migration guests and
Proxmox overhead. Phase 6 must measure actual and peak memory use before each build and preserve a
host reserve. `media01` is not created if the admission check predicts unsafe memory pressure.
Increasing the server to 64 GiB is recommended before adding optional applications or full metrics
and log-retention stacks, but is not assumed by the plan.

## Deferred applications

The following are outside the initial build unless a later GitHub issue supplies a use case, data
owner, resource budget, exposure rule, backup, and restore test:

- the Arr application family and download clients;
- Authentik in place of the lighter Authelia baseline;
- Prometheus, Grafana, and Loki retention stacks;
- Vaultwarden, Paperless-ngx, Home Assistant, and general-purpose automation services;
- a general experimental Docker host; and
- any application found on `udms01` or `udms02` that is not explicitly adopted.

Pi-hole or AdGuard are not added beside Technitium. Portainer, Watchtower, and uncontrolled
automatic application updates are not part of the managed baseline.

## References

- [Community Scripts](https://community-scripts.org/)
- [community-scripts/ProxmoxVE](https://github.com/community-scripts/ProxmoxVE)
- [SimpleHomelab](https://www.simplehomelab.com/)
- [SimpleHomelab/Deployrr](https://github.com/SimpleHomelab/Deployrr)
- [ChrispyBacon-dev/DockFlare](https://github.com/ChrispyBacon-dev/DockFlare)
- [Immich Docker Compose](https://docs.immich.app/install/docker-compose/)
