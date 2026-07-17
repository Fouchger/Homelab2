# Phase 6 automated build plan

Phase 6 implements the accepted future state in [`FUTURE_STATE.md`](FUTURE_STATE.md). Work is
delivered through GitHub issues and pull requests in dependency order. A workstream may build a
replacement but may not retire, stop, delete, or mutate a discovered existing server.

## Operator experience

The target workflow is one guarded operation with resumable stages:

1. Load and validate the encrypted site manifest.
2. Discover the live router and Proxmox state.
3. Refuse address, VMID, storage, or ownership collisions.
4. Show a human-readable plan and save machine-readable evidence.
5. Build approved replacements, import them into OpenTofu ownership, and require zero-change plans.
6. Configure applications without interactive installer sessions.
7. Run health, network, storage, backup, and restore checks.
8. Pause at cutover checkpoints that require operator approval.
9. Produce comparison and manual-retirement reports.

Every stage is idempotent and independently resumable. Failure leaves the existing service in
place and records a sanitized diagnostic report.

## Workstreams

### 6.0 Governance, manifest, and safety engine

Deliver:

- a versioned whole-homelab manifest for networks, guests, applications, exposure, and backups;
- grouped VMID allocation beginning at 200 and the per-VLAN static/DHCP address policy;
- Ubuntu 24.04 defaults with documented operating-system exceptions;
- discovered-resource protection markers and immutable VMID/disk deny lists;
- resource admission checks for memory, storage, addresses, and VMIDs;
- plan, apply, resume, and evidence contracts shared by the CLI and control panel;
- GitHub issue templates and the Phase 6 milestone; and
- fixtures proving that discovered guests cannot enter a destroy or replace plan.

Acceptance: a synthetic and production read-only discovery run produces a complete plan and every
destructive mutation against a discovered guest is refused before provider execution.

### 6.1 MikroTik desired state and recovery

Deliver:

- normalized RouterOS inventory and a secret-free desired-state model;
- VLAN, bridge, Wi-Fi, DHCP, DNS, firewall, NAT, service, WireGuard, and NTP adapters;
- duplicate-rule and unsafe-rule detection;
- reviewed incremental commands with Safe Mode and rollback instructions; and
- laptop recovery and wired management-port acceptance.

Acceptance: every VLAN receives the intended DHCP, DNS, internet, isolation, and management policy;
the production ruleset has no duplicate input blocks; and a current encrypted router backup exists.

### 6.2 Pinned Community Scripts integration

Deliver:

- an upstream manifest containing repository commit, script path, checksum, license, and metadata;
- safe retrieval and verification without `curl | bash` from a moving branch;
- generated user/app defaults for unattended VM and LXC creation;
- sanitized streaming logs, timeouts, failure quarantine, and created-resource adoption evidence;
- automatic OpenTofu import from captured Proxmox configuration followed by a zero-change plan;
- dry-run metadata inspection and collision refusal; and
- test adapters for a disposable guest before production use.

Acceptance: a disposable guest is created from a reviewed script without wizard input, passes the
expected health checks, imports without OpenTofu drift, and a repeated run safely reports the
existing accepted result. Failed creations are reported and never deleted automatically.

### 6.3 Replacement control plane

Deliver:

- `control01` beside the current control plane;
- locked Homelab2 installation, automation SSH identity, and new SOPS/age identity;
- offline identity-backup verification;
- least-privilege MikroTik, Proxmox, Cloudflare, and guest credentials; and
- a recovery test from repository plus encrypted recovery material.

Acceptance: `control01` can discover, validate, plan, decrypt, authenticate, derive inventory, and
export diagnostics without depending on the existing control-plane container.

### 6.4 Replacement DNS

Deliver:

- `dns01` through a pinned Technitium Community Scripts adapter;
- forward and reverse zones, recursion/forwarding, filtering policy, and configuration backup;
- MikroTik DHCP transition planning;
- per-VLAN DNS and failure tests; and
- split-DNS entries for internal Traefik routes.

Acceptance: the replacement answers from every intended VLAN, failure behavior is known,
configuration restores successfully, and both old DNS guests remain running.

### 6.5 Edge Docker platform

Deliver:

- `edge01` through the pinned Community Scripts Docker VM path;
- Deployrr-compatible directories, networks, Compose projects, and version pins;
- socket proxy, Traefik, DockFlare, cloudflared, Authelia, session storage, CrowdSec, Uptime Kuma,
  Homepage, and Dozzle;
- internal/external entry-point separation and exposure allowlists;
- Cloudflare/OpenTofu/DockFlare ownership-conflict detection; and
- application, certificate, authentication, and tunnel health tests.

Acceptance: internal routes resolve through Technitium and Traefik; an approved test application
works through Cloudflare Access without router port forwarding; management endpoints remain
unpublished; and the stack rebuilds from Git plus secrets.

### 6.6 OpenMediaVault adoption and backup foundation

Deliver:

- read-only inventory of raw disks, Btrfs filesystems, shares, permissions, users, jobs, and health;
- explicit OMV address and VLAN 70 design without changing disk ownership;
- NFS mounts with startup dependencies for managed consumers;
- Proxmox backup storage and retention policy; and
- system-disk, configuration, and sample restore validation.

Acceptance: every disk identifier and share has an owner, no host-side disk mutation is planned,
managed consumers can recover mounts after restart, and a test backup restores outside production.

### 6.7 Managed Plex consolidation

Deliver:

- inventory and backup of both existing Plex databases, identities, libraries, mounts, users, and purpose;
- an operator-approved canonical identity and explicit consolidation map;
- one Plex service in the `media01` Compose project;
- OMV media mounts and least-write access;
- planned GPU passthrough and shared `/dev/dri` access inside the VM;
- local, remote, direct-play, transcode, and rollback tests; and
- a comparison report while both old Plex LXCs remain present.

Acceptance: the single Plex service preserves the accepted canonical identity, required state, and
media access; software validation passes before the GPU handover; hardware transcoding passes after
the approved checkpoint; and both old LXCs remain available for operator-controlled rollback.

### 6.8 Managed Immich rebuild

Deliver:

- database, media, external-library, machine-learning, user, and version inventory;
- verified database and media recovery set;
- official Immich Compose services on `media01` with PostgreSQL on local SSD;
- accepted OMV library placement, permissions, GPU access, proxy settings, and backup hooks; and
- automated asset-count, database, thumbnail, upload, search, and mobile-client validation.

Acceptance: a restored copy passes application and user-visible validation before any DNS change;
cutover is explicitly approved; and the old Immich LXC remains untouched.

### 6.9 Recovery, observability, and full acceptance

Deliver:

- Uptime Kuma monitors and alert tests for router, Proxmox, DNS, OMV, edge, Plex, and Immich;
- backup schedules, retention, failure alerts, and restore-test evidence;
- router, control-plane, DNS, edge, Plex, and Immich recovery runbooks;
- startup dependency checks after an orderly host restart;
- a capacity and security review; and
- manual-retirement reports for replaced guests.

Acceptance: the accepted recovery drills work from documented material, monitoring detects a safe
test failure, all required services recover after the controlled restart, and no discovered guest
was stopped or deleted by Homelab2.

## Development contract for every workstream

Every implementation issue must include:

- desired and explicitly excluded behavior;
- dependency and ownership declarations;
- plan/check/apply behavior using one shared implementation;
- pinned upstream provenance and checksums where external scripts or artifacts are used;
- secret redaction and failure handling;
- unit tests, offline fixtures, and proportionate disposable/live acceptance;
- idempotence and resume tests;
- backup, restore, rollback, and health checks;
- operator documentation; and
- sanitized acceptance evidence in the GitHub issue or pull request.

No pull request may combine an application build with retirement of its predecessor.

## GitHub workflow

- Milestone: `v0.6.0 - Phase 6: Automated homelab build`.
- Tracking issue: [#27](https://github.com/Fouchger/Homelab2/issues/27).
- Each workstream has its own issue and acceptance criteria.
- Development branches use `codex/issue-<number>-<short-name>`.
- Pull requests link their issue and remain focused on one reviewable capability.
- GitHub Actions must pass before merge.
- Production evidence is added only after secrets, tokens, public addresses, user data, and private
  keys have been removed.
- An issue closes only after its automated tests, documentation, and required live acceptance pass.
- The milestone closes only after workstream 6.9 and the release checklist pass.

Issue state is the progress authority. This document records sequencing and acceptance boundaries;
it does not duplicate day-to-day status.

| Workstream | GitHub issue |
|---|---|
| 6.0 Governance, manifest, and safety engine | [#17](https://github.com/Fouchger/Homelab2/issues/17) |
| 6.1 MikroTik desired state and recovery | [#18](https://github.com/Fouchger/Homelab2/issues/18) |
| 6.2 Pinned Community Scripts integration | [#19](https://github.com/Fouchger/Homelab2/issues/19) |
| 6.3 Replacement control plane | [#20](https://github.com/Fouchger/Homelab2/issues/20) |
| 6.4 Replacement DNS | [#21](https://github.com/Fouchger/Homelab2/issues/21) |
| 6.5 Edge Docker platform | [#22](https://github.com/Fouchger/Homelab2/issues/22) |
| 6.6 OpenMediaVault and backup foundation | [#23](https://github.com/Fouchger/Homelab2/issues/23) |
| 6.7 Managed Plex consolidation | [#24](https://github.com/Fouchger/Homelab2/issues/24) |
| 6.8 Managed Immich rebuild | [#25](https://github.com/Fouchger/Homelab2/issues/25) |
| 6.9 Recovery and release acceptance | [#26](https://github.com/Fouchger/Homelab2/issues/26) |

## Release boundaries

Phase 5 (`v0.5.0`) is architecture and planning only. It makes no production infrastructure
changes. Phase 6 (`v0.6.0`) contains the guarded build implementation and production acceptance.
Optional applications and operator-performed old-server retirement are not required for `v0.6.0`.
