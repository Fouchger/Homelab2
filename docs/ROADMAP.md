# Homelab2 delivery roadmap

Phase 6 completed the planning, manifest, read-only discovery, and no-destroy safety foundation.
The remaining production work is now delivered through Phases 7–11 in the
[Homelab2 Roadmap](https://github.com/users/Fouchger/projects/2).

GitHub tracker issues are the progress authority. This document records stable sequence,
dependencies, acceptance boundaries, and the engineering contract shared by every phase. A phase
may build a replacement but may not retire, stop, delete, or mutate a discovered existing server.

## Completed foundation

[Phase 6](https://github.com/Fouchger/Homelab2/issues/17) delivered the versioned whole-site
manifest and schema, future-state architecture, resource admission, immutable resource
protections, provider-independent no-destroy planning, and secret-redacted read-only discovery
evidence. It performed no router, replacement-guest, storage, or application production mutation.

## Active delivery sequence

### Phase 7: network and control foundation

Tracker: [#31](https://github.com/Fouchger/Homelab2/issues/31)

Objective: deliver the safe network and control-plane foundation required by every later phase.

Ordered scope:

1. [#36](https://github.com/Fouchger/Homelab2/issues/36) — align repository documentation with
   the Phase 7–11 roadmap.
2. [#3](https://github.com/Fouchger/Homelab2/issues/3) — CLI and clean-machine installer
   acceptance.
3. [#11](https://github.com/Fouchger/Homelab2/issues/11) — offline age identity backup and
   recovery.
4. [#12](https://github.com/Fouchger/Homelab2/issues/12) — trusted Proxmox TLS.
5. [#18](https://github.com/Fouchger/Homelab2/issues/18) — MikroTik desired state, backup,
   rollback, and reconciliation.
6. [#19](https://github.com/Fouchger/Homelab2/issues/19) — pinned Community Scripts creation and
   OpenTofu adoption.
7. [#20](https://github.com/Fouchger/Homelab2/issues/20) — replacement `control01` build and
   recovery.

Dependency: the completed Phase 6 safety foundation.

Exit criteria:

- Repository documentation and GitHub planning describe the same active roadmap.
- Router configuration is reproducible with tested wired recovery and rollback.
- Pinned guest creation and OpenTofu adoption pass on a disposable workload.
- Replacement `control01` rebuilds from Git plus encrypted recovery material.
- Offline age recovery, trusted Proxmox TLS, and installer acceptance pass.
- No discovered production guest or storage resource is stopped, replaced, or deleted.
- Tests, documentation, and sanitized acceptance evidence are current.

### Phase 8: core services and edge

Tracker: [#32](https://github.com/Fouchger/Homelab2/issues/32)

Objective: replace core DNS safely and establish the managed edge-routing platform.

Ordered scope:

1. [#16](https://github.com/Fouchger/Homelab2/issues/16) — control-panel action visibility.
2. [#21](https://github.com/Fouchger/Homelab2/issues/21) — replacement Technitium DNS.
3. [#22](https://github.com/Fouchger/Homelab2/issues/22) — Deployrr-compatible `edge01` with
   Traefik and DockFlare.

Dependency: Phase 7 network and control foundation.

Exit criteria:

- Replacement DNS passes forward, reverse, recursive, filtering, restore, and per-VLAN tests.
- DHCP DNS transition and rollback are proven without retiring existing DNS guests.
- Edge stack rebuilds unattended from Git plus encrypted secrets.
- Internal routing and one approved Cloudflare Access test route pass.
- Management and non-allowlisted services remain externally unreachable.
- Backup, restore, idempotence, rollback, tests, and documentation pass.

### Phase 9: storage and backup

Tracker: [#33](https://github.com/Fouchger/Homelab2/issues/33)

Objective: integrate existing storage without changing disk ownership and establish tested backup
and recovery foundations.

Ordered scope:

1. [#23](https://github.com/Fouchger/Homelab2/issues/23) — safe OpenMediaVault adoption and backup
   storage.
2. [#15](https://github.com/Fouchger/Homelab2/issues/15) — disposable curated-application
   recovery validation.

Dependencies: Phase 7 replacement control plane. Phase 8 is required before edge-service backup
acceptance.

Exit criteria:

- Every OpenMediaVault disk, filesystem, share, user, and consumer has an explicit owner.
- No host-side disk mutation or destructive storage action appears in any plan.
- Managed mounts, backup schedules, retention, alerts, and a sample restore pass.
- Uptime Kuma update, rollback, rebuild, and persistent-data restore pass on a disposable workload.
- Existing `omv01` and its passed-through data disks remain intact.
- Recovery evidence contains no secrets or production data.

### Phase 10: media migration

Tracker: [#34](https://github.com/Fouchger/Homelab2/issues/34)

Objective: consolidate Plex and rebuild Immich on the managed media platform without retiring
protected source systems.

Ordered scope:

1. [#24](https://github.com/Fouchger/Homelab2/issues/24) — one managed Plex service on `media01`.
2. [#25](https://github.com/Fouchger/Homelab2/issues/25) — managed Immich rebuild and restore on
   `media01`.

Dependencies: Phase 8 edge services and Phase 9 storage and backup foundation.

Exit criteria:

- Canonical Plex identity and required source state are explicitly selected and backed up.
- Plex libraries, users, watch state, media access, hardware transcoding, and rollback pass.
- Immich database, uploads, external libraries, and application revision are inventoried and
  backed up.
- Immich restore, GPU acceleration, health, backup, and rollback pass.
- Capacity admission preserves the required Proxmox host reserve.
- Existing Plex and Immich guests remain available until manual operator retirement.

### Phase 11: recovery and release

Tracker: [#35](https://github.com/Fouchger/Homelab2/issues/35)

Objective: prove that the completed homelab is observable, recoverable, secure, capacity-safe, and
ready for release.

Ordered scope:

1. [#26](https://github.com/Fouchger/Homelab2/issues/26) — full recovery, observability, and release
   acceptance.

Dependencies: Phases 7, 8, 9, and 10 must be accepted.

Exit criteria:

- Monitoring detects and clears controlled failures.
- Router, control plane, DNS, edge, storage, Plex, and Immich restore drills pass.
- An orderly Proxmox restart restores services in documented dependency order.
- Capacity, exposure, secrets, ownership, backup, and no-destroy audits pass.
- Full automated quality suite and release documentation pass.
- Manual-retirement reports are produced; Homelab2 performs no automatic retirement.

## Development contract

Every implementation issue must declare desired and excluded behavior, dependencies, ownership,
plan/check/apply behavior, secret handling, failure handling, and upstream provenance. It must add
focused tests and proportionate disposable or live acceptance, including idempotence, resume,
backup, restore, rollback, health, operator documentation, and sanitized evidence where relevant.

No pull request may combine a replacement build with retirement of its predecessor. Production
evidence must exclude secrets, tokens, public addresses, private topology, user data, and private
keys. An issue closes only after its automated checks, documentation, and required live acceptance
pass.

## Operator experience

The target workflow remains one guarded, resumable operation: validate the encrypted manifest,
discover live state, refuse collisions or ownership violations, save a human- and machine-readable
plan, build only approved replacements, adopt created resources into OpenTofu with zero drift,
configure them unattended, run health and recovery checks, pause at operator cutovers, and produce
comparison and manual-retirement reports. Failure leaves the existing service in place and records
sanitized diagnostics.
