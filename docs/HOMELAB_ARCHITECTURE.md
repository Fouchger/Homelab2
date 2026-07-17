# Whole-homelab architecture

This document defines the target homelab from the physical edge inward. Homelab2 is intended to
build and operate the network, Proxmox platform, core services, and applications while preserving
clear ownership boundaries and recoverability.

The complete application catalogue, deployment choices, exposure matrix, and tool boundaries are
defined in [`FUTURE_STATE.md`](FUTURE_STATE.md). The Phase 6 implementation sequence is defined in
[`PHASE_6_EXECUTION_PLAN.md`](PHASE_6_EXECUTION_PLAN.md).

## Hardware boundary

The current site has three physical systems:

- one MikroTik hAP ax2 router;
- one Proxmox VE server; and
- one Windows laptop used for bootstrap, recovery, and administration.

There is no second hypervisor or dedicated backup server. Multiple guests on the Proxmox host can
protect against a service process failure, but they do not provide physical-host availability.

## Network plan

The existing VLAN and address structure is retained as the starting contract.

| VLAN | Subnet | Purpose | Gateway |
|---:|---|---|---|
| 10 | ISP assigned | WAN handoff | ISP assigned |
| 20 | `192.168.20.0/24` | Management | `192.168.20.1` |
| 30 | `192.168.30.0/24` | Servers | `192.168.30.1` |
| 40 | `192.168.40.0/24` | Trusted users | `192.168.40.1` |
| 50 | `192.168.50.0/24` | IoT | `192.168.50.1` |
| 60 | `192.168.60.0/24` | Guests | `192.168.60.1` |
| 70 | `192.168.70.0/24` | Storage and backup | `192.168.70.1` |
| 90 | `192.168.90.0/24` | DMZ and ingress | `192.168.90.1` |

The Proxmox VLAN-aware bridge carries VLANs 20, 30, and 70. The Proxmox host remains at
`192.168.20.10`. RouterOS owns gateways, DHCP, Wi-Fi, routing, NAT, and the inter-VLAN firewall.

Static infrastructure and server addresses use host numbers `.1-.99`. Host numbers `.100-.200`
are reserved outside normal pools. DHCP uses `.201-.254`. Existing assignments are transitioned
only through reviewed, non-disruptive changes.

## Managed VMID groups

All new guests start at VMID 200 and are grouped by responsibility. Discovered VMIDs are protected
and never reused. `omv01` remains VMID 22000.

| VMID range | Type | Planned resource |
|---:|---|---|
| 200-219 | Control and management | `control01` = 201 |
| 220-239 | DNS and network core | `dns01` = 220 |
| 240-299 | Edge and operations | `edge01` = 240 |
| 300-399 | Storage and backup | Reserved; `omv01` stays 22000 |
| 400-499 | Media and photos | `media01` = 400 |
| 500-599 | General applications | Future managed applications |
| 600-699 | Monitoring and security | Reserved |
| 700-799 | Disposable validation | Test guests only |
| 800-899 | Infrastructure expansion | Reserved |

## Retained workloads

Only the following existing workloads cross the clean-build boundary.

| VMID | Workload | Network | Address | Lifecycle |
|---:|---|---|---|---|
| 22000 | `omv01` | VLAN 30 | DHCP, to be made explicit | Preserve and adopt |
| 21010 | `plex01` | VLAN 30 | `192.168.30.30` | Preserve and adopt |
| 21011 | `plex02` | VLAN 30 | `192.168.30.31` | Preserve and adopt |
| 100000 | `immich` | VLAN 30 | DHCP, to be made explicit | Preserve until managed rebuild |

These resources are legacy-adopted workloads. Homelab2 may validate and document them, but it may
not recreate, replace, resize, detach storage from, stop, or destroy the existing resources. A
future managed replacement must use a separate resource and leave retirement to the operator.

### OpenMediaVault storage boundary

`omv01` is a protected VM with a 32 GiB system disk and five physical disks passed directly by
stable disk identifier. The approximate physical capacities are 10 TB, 10 TB, 5 TB, 4 TB, and
16 TB. The host detects Btrfs signatures on the raw disks.

The physical disks and their filesystems belong exclusively to OpenMediaVault. Proxmox,
OpenTofu, installers, and host-side storage automation must never initialize, format, pool, mount,
or otherwise claim them. Any future change requires an OpenMediaVault configuration export,
filesystem health evidence, an independent data backup, and an explicit storage migration plan.

### Plex boundary

Both Plex containers are protected Ubuntu LXCs with four CPU cores, 4 GiB RAM, 50 GiB root disks,
GPU render-device access, NFS/CIFS support, and optional serial/USB device bindings. Their media
mounts are expected to be configured inside the containers and must be inventoried before any
OpenMediaVault or network change.

The current Plex LXCs are protected migration sources. The future target is one Plex container in
the managed `media01` Docker VM. Both sources are inventoried and backed up, then the operator
selects the canonical identity and required state to consolidate. The single passed-through GPU is
shared inside `media01` with Immich.

The intended startup dependency is:

1. core DNS;
2. `omv01`;
3. the managed Plex service after storage is available.

### Immich boundary

`immich` remains protected until its database, upload library, external-library mounts, machine
learning data, application revision, and recovery procedure have been inventoried and backed up.
Its future managed replacement must prove database and media restoration before Homelab2 presents
the existing container to the operator as a manual-retirement candidate.

## Replaceable workloads

The following current guests are not part of the preserved state and will be retired only after
their required replacements or dependencies have been accepted:

| VMID | Current workload | Retirement prerequisite |
|---:|---|---|
| 100 | `homelab-control` | Replacement control plane accepted |
| 200 | `monitoring` | No prerequisite; preserve useful configuration evidence only |
| 20000 | `apt-cacher-ng` | Confirm no guest package configuration depends on it |
| 20011 | `udms01` | Confirm no required data or client dependency |
| 20012 | `udms02` | Confirm no required data or client dependency |
| 21001 | `dns01` | Replacement DNS serving every VLAN |
| 21002 | `dns02` | Replacement DNS serving every VLAN |

Being replaceable does not authorize Homelab2 to stop or delete a server. Homelab2 may build and
validate a replacement and produce a retirement checklist, but only the operator may manually
stop, delete, or destroy an existing server after accepting its replacement.

## No-destroy boundary

Homelab2 must never execute a stop, delete, destroy, replacement, disk-removal, or storage-reclaim
operation against any server discovered in the existing environment. This applies to retained and
replaceable workloads alike. Replacement acceptance and old-server retirement are distinct:

1. Homelab2 builds and validates the replacement without changing the existing server.
2. The operator compares both systems and decides when the replacement is satisfactory.
3. The operator performs any shutdown or deletion manually outside the automated workflow.

Automated plans must refuse an action that would destroy a discovered server, even if the server
has been marked replaceable in the architecture.

## Target service layers

The clean build proceeds in dependency order.

1. **Network foundation:** MikroTik WAN, management access, VLANs, DHCP, DNS forwarding, Wi-Fi,
   firewall, NAT, NTP, and encrypted recovery backups.
2. **Platform foundation:** Proxmox host validation, trusted TLS, VLAN-aware bridge, storage
   boundaries, API identity, and a replacement control-plane container.
3. **Core services:** one freshly configured internal DNS server, forward and reverse zones, and
   explicit public/private DNS ownership.
4. **Preserved services:** adopt and validate `omv01`, `plex01`, `plex02`, and `immich` without
   changing their lifecycle or data; rebuild Immich only after restore acceptance.
5. **Operations:** monitoring, configuration backup, guest backup, alerting, certificate lifecycle,
   and recovery testing.
6. **Applications:** add only reviewed applications with explicit data, DNS, network, backup, and
   ownership contracts.

## Ownership

| Resource | Owner |
|---|---|
| VLANs, DHCP, Wi-Fi, routing, firewall, NAT | MikroTik workflow |
| Proxmox guest lifecycle | OpenTofu |
| Retained legacy guest lifecycle | Manual protection until separately adopted |
| Guest operating-system configuration | Ansible |
| Internal DNS | Curated DNS adapter |
| Public DNS | OpenTofu and Cloudflare |
| Application configuration | Curated application adapter |
| Runtime secrets | SOPS and age |
| OpenMediaVault raw disks and filesystems | OpenMediaVault only |

Public tunnel ingress and Cloudflare Access applications are owned by DockFlare. OpenTofu and
DockFlare must use disjoint record identities. Deployrr provides Docker templates and conventions;
Homelab2 owns their accepted, pinned deployment representation.

Every address, DNS record, guest, disk, and application must have exactly one owner.

## Rebuild objective

The homelab is reproducible when working hardware, the Git repository, encrypted runtime state,
and an offline recovery pack are sufficient to rebuild the router, Proxmox control plane, core
DNS, and managed services, then reconnect the protected OpenMediaVault, Plex, and Immich workloads
without data loss or undocumented configuration.
