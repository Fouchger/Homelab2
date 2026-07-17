# Clean rebuild and adoption plan

This plan treats the existing Proxmox host as a clean-build platform while preserving `omv01`,
`plex01`, `plex02`, and `immich`. It deliberately avoids a Proxmox reinstall: with one physical
host and no independent backup server, reinstalling the host before validated off-host recovery
would put the retained workloads and OpenMediaVault data at unnecessary risk.

## Safety invariants

- Never stop, delete, destroy, or replace any discovered server, including VMIDs 22000, 21010,
  21011, and 100000. Retirement is performed manually by the operator after replacement acceptance.
- Never initialize, format, mount, or import the five OpenMediaVault raw disks on the Proxmox host.
- Keep the current control plane alongside its replacement and leave its retirement to the operator.
- Keep both current DNS servers until replacement DNS works from every VLAN, then leave their
  retirement to the operator.
- Never change router VLAN or firewall behavior without direct laptop recovery access, a current
  redacted export, an encrypted binary backup, a reviewed difference, and a rollback command.
- Never represent a discovered resource as managed until its desired configuration matches the
  accepted live behavior.

## Stage 0: preserve the retained workloads

Before infrastructure cleanup:

1. Export the current Proxmox definitions for VMIDs 22000, 21010, 21011, and 100000.
2. Record the stable identifiers, SMART health, and OpenMediaVault ownership of every passed disk.
3. Export the OpenMediaVault configuration and record its current address.
4. Record OpenMediaVault filesystems, Btrfs layout, shared folders, SMB/NFS exports, users, groups,
   permissions, scheduled jobs, and notification settings.
5. Record the live mounts inside both Plex containers, including `/etc/fstab`, mount options,
   credentials-file locations, and media paths.
6. Back up both Plex application-data directories and verify that each backup can be read.
7. Create recoverable backups of the Plex root disks and the OpenMediaVault system disk without
   treating those backups as copies of the raw media disks.
8. Record the Immich database, upload library, external-library mounts, application revision,
   machine-learning data, and current backup coverage.
9. Create and verify an Immich database-and-media recovery set.
10. Verify that Proxmox protection remains enabled on all four retained guests.

Stage 0 is complete only when loss of a guest system disk would not require guessing how to
reconnect the existing media filesystems.

## Stage 1: normalize the MikroTik foundation

1. Preserve the current RouterOS export, runtime inventory, and encrypted binary backup.
2. Keep the temporary VLAN 20 recovery rule until a clean ruleset is accepted.
3. Model the existing ports, VLANs, DHCP networks, Wi-Fi profiles, services, firewall, and NAT.
4. Remove duplicated firewall blocks through a reviewed, narrow maintenance operation.
5. Restrict brute-force tracking to WAN before the blacklist drop.
6. Restore complete bridge membership for management, IoT, and guest Wi-Fi on both radios.
7. Verify from each available network: DHCP, gateway, DNS, internet access, intended isolation, and
   management denial or access.
8. Verify router recovery from the Windows laptop over a known wired management port.

The first managed RouterOS render must target the accepted current behavior rather than introduce
unrelated network redesign.

## Stage 2: bootstrap the new control plane

1. Build a new, minimal Ubuntu 24.04 control-plane container alongside the current one.
2. Give it a temporary explicit management address on VLAN 20.
3. Install Homelab2 from the locked repository revision.
4. Create a new automation SSH identity and a new SOPS/age identity.
5. Store the age identity in an encrypted offline recovery location before adding provider tokens.
6. Establish separate least-privilege credentials for MikroTik inspection, Proxmox bootstrap,
   Proxmox API access, Cloudflare, and guest automation.
7. Validate the router and Proxmox in observation-only mode.
8. Present the old control plane as a manual-retirement candidate only after the new one can
   validate configuration, decrypt credentials, authenticate to Proxmox, produce plans, derive
   inventory, and export diagnostics.

## Stage 3: rebuild core DNS

1. Define the internal namespace, reverse zones, forwarding policy, and public/private ownership.
2. Build replacement DNS services on temporary addresses so the existing servers remain online.
3. Import only reviewed zones and records; do not import undocumented historical configuration.
4. Verify recursive, forward, reverse, and failure behavior from every VLAN.
5. Change MikroTik DHCP DNS settings through a reviewed transition.
6. Observe client renewal and resolution before moving the replacement servers to their final
   identities or presenting VMIDs 21001 and 21002 as manual-retirement candidates.

## Stage 4: adopt OpenMediaVault and rebuild Plex and Immich

1. Give `omv01` an explicit reserved or static address without changing its disk ownership.
2. Validate all OpenMediaVault arrays/filesystems, shares, permissions, and health reporting.
3. Validate existing Plex media mounts, GPU access, database health, libraries, accounts, users,
   watch state, and remote-access policy.
4. Build the two managed Plex containers on `media01`, restore copies of their application data,
   validate both identities, and perform the GPU handover only at an approved checkpoint. Leave the
   existing Plex LXCs untouched for operator-controlled rollback and retirement.
5. Encode monitoring and backup checks without placing the retained guests under destructive
   OpenTofu lifecycle control.
6. Test the dependency startup sequence and recovery after an orderly host restart.
7. Build a managed Immich replacement alongside the current container, restore its database and
   media, validate application health and user-visible assets, then cut over while leaving the
   original container untouched for operator-controlled retirement.

## Stage 5: validate replacements and hand off retirement

For each replaceable guest, Homelab2 may:

1. Identify consumers, DNS records, mounts, credentials, and data.
2. Preserve only the evidence or data explicitly required by the new design.
3. Build and validate its replacement alongside the existing server.
4. Report the exact Proxmox resource, disks, snapshots, backups, consumers, and DNS records that a
   future manual retirement would affect.
5. Produce a retirement checklist and wait for the operator to compare both systems.

Homelab2 must not stop or delete the old guest. When satisfied that the replacement works properly,
the operator may retire the old guest manually through Proxmox. Manual retirement is outside the
automated Phase 5 workflow and is not required for Phase 5 acceptance.

## Stage 6: add operations and applications

Add monitoring, trusted certificates, backups, and applications only after the network, control
plane, DNS, storage, and retained workloads are stable. Each new service requires an owner, VLAN,
address, DNS records, firewall paths, persistent-data boundary, backup method, restore test,
health check, update procedure, and rollback procedure.

## Acceptance

The clean rebuild is accepted when:

- the router configuration is reproducible and no temporary recovery rule remains;
- the new control plane can recover from its offline identity and repository state;
- trusted Proxmox API access and non-destructive planning pass;
- internal DNS works from every VLAN and public DNS has an explicit owner;
- OpenMediaVault exposes every accepted filesystem and share without disk changes;
- both Plex servers retain their application state, media access, and GPU functionality;
- Immich passes a database-and-media restore into its managed replacement before cutover;
- every replacement has acceptance evidence while its previous server remains untouched; and
- the documented recovery procedure can reconstruct managed services without relying on memory.
