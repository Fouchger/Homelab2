# Phase 6 manifest and safety foundation

`config/examples/future-state.yaml` is the first complete machine-validated representation of the
approved target. It is separate from the legacy `site.yaml` provisioning input so current Phase 3
commands continue to work while Phase 6 adapters are developed.

The manifest records networks, guests, applications, exposure, backups, ownership, migration
state, stable usernames, SOPS secret references, and host-capacity limits. It enforces:

- Ubuntu 24.04 for new guests unless an exception reason is committed;
- grouped VMIDs from 200 through 899, with `omv01` retained at VMID 22000;
- static server addresses in `.1-.99`, a reserved `.100-.200` range, and DHCP in `.201-.254`;
- exactly one owner for each guest, application, exposure, address, VMID, and raw disk;
- backup and restore-test declarations for every stateful application; and
- SOPS references in Git rather than passwords, tokens, or private keys.

Credential references use `sops://credentials.<key>.value`. The decrypted production bundle keeps
one value per key, refuses placeholder or duplicate values, and must contain every key referenced
by the manifest. This preserves accepted service credentials across rebuilds without creating a
universal homelab password.

The provider-independent safety engine evaluates discovery before any provider call. A discovered
or protected guest can never enter a stop, destroy, or replace action. A discovered or protected raw
disk can never enter detach, reclaim, destroy, or replace. New VMID/address collisions and unsafe
memory or storage pressure are also refused.

Plan, apply, resume, and evidence contracts carry immutable digests between the CLI and control
panel. Apply remains disabled unless a later operator checkpoint explicitly enables production
mutation. Evidence rejects common secret-bearing fields.

For Phase 6.0, validation uses synthetic discovery fixtures only. Live router and Proxmox access
remains read-only, and no existing guest is stopped, deleted, detached, or replaced.
