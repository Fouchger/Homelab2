# MikroTik existing-configuration audit

Audit date: 2026-07-20

This is a read-only audit of the existing hAP ax2 configuration. It does not authorize or perform
any RouterOS mutation. The audit supports Phase 07.5 issue #18 and covers the router as one system:
WAN, bridge ports, all VLANs, Wi-Fi, DHCP, DNS, routing, firewall, NAT, management services,
WireGuard, NTP, and recovery.

## Evidence boundary

The audit uses the latest locally captured snapshots:

- `discovery-output/20260721-050418/mikrotik-export-redacted.rsc`
  (SHA-256 `92CCEA7346D6DE18927C985A0ACC08A83F5961C86DD92703BB7B6B907B989995`)
- `discovery-output/20260721-050418/mikrotik-runtime-redacted.txt`
  (SHA-256 `6BA42EB7E56EDE1998F591D8A5EDEA1FFE542D3320A5061B51F8A76761C6999F`)
- `discovery-output/20260721-050418/proxmox-redacted.txt`
  (SHA-256 `4454714EF98C901E8AD4BA320ED4DC563023A1D5F04A717EEE91D16B11028F37`)

The snapshots are ignored by Git and have not been committed. The current collector used normal
RouterOS `/export`, redacted quoted multiline and unquoted secret-shaped assignments locally, and
passed its fail-closed residual-secret check before writing the files. The earlier 2026-07-17
snapshot remains unsafe because it contained a scheduled-command backup password; it must not be
shared, and that historical credential still requires rotation.

The snapshot records RouterOS 7.23.2 on a MikroTik hAP ax2. Runtime counters represent only the
short observation window after the recorded router restart and are supporting evidence, not a
complete traffic history.

MikroTik's official stable changelog was checked on 2026-07-21 and lists RouterOS 7.23.2 as the
current stable release. The router therefore does not need a version change before reconciliation.
The complete no-apply contract is documented in `docs/MIKROTIK_DESIRED_STATE.md`.

## Current topology

| VLAN | Role | Gateway | Current attachment | DHCP | Router DNS input |
|---:|---|---|---|---|---|
| 10 | WAN | DHCP/CGNAT | tagged on `ether1` | WAN client | not applicable |
| 20 | Management | `192.168.20.1` | `ether2` trunk, `ether3` access, management Wi-Fi | enabled | allowed |
| 30 | Servers | `192.168.30.1` | `ether2` trunk | enabled | **blocked** |
| 40 | Trusted users | `192.168.40.1` | `ether2` trunk, `ether4/5` access, users Wi-Fi | enabled | allowed |
| 50 | IoT | `192.168.50.1` | Wi-Fi only in the captured bridge table | enabled | allowed |
| 60 | Guests | `192.168.60.1` | Wi-Fi only in the captured bridge table | enabled | allowed |
| 70 | Storage | `192.168.70.1` | `ether2` trunk | enabled | **blocked** |
| 90 | DMZ | `192.168.90.1` | `ether2` trunk | enabled | **blocked** |

The bridge uses VLAN filtering. `ether2` is the tagged Proxmox trunk, `ether3` is intended as the
wired management recovery port, and `ether4/5` are untagged trusted-user ports. IPv6 is disabled.

## Findings

### Critical: the old redacted export contains a secret

The daily binary-backup scheduler embeds its password in a multiline command. The old collection
did not remove it. A daily `show-sensitive` text export is also stored on the router itself.

Required correction:

1. rotate the binary-backup password;
2. stop treating the old export as safe evidence;
3. use the current fail-closed collector and verify it refuses residual secret-shaped values;
4. replace local-only backups with encrypted off-router recovery copies;
5. prove recovery before changing bridge, VLAN, or firewall behavior.

### High: DNS policy is internally inconsistent and blocks the baseline

The router forwards its own DNS queries to the two existing Technitium guests at
`192.168.30.2` and `192.168.30.3`. DHCP advertises those two guests plus each VLAN gateway.
Firewall input rules allow DNS to the router from management, users, IoT, and guest VLANs, but not
from servers, storage, or DMZ.

The managed `monitoring` guest is on VLAN 30 and was configured to use `192.168.30.1` only. Its DNS
requests therefore reach the router's final input drop. This explains the repeated `apt-get update`
timeout without requiring a package or Ansible defect.

Required correction:

- choose and document one DNS policy for every VLAN: direct Technitium, router forwarding, or a
  deliberate ordered combination;
- validate both existing DNS services directly before changing clients;
- make firewall input rules and DHCP/static guest settings match that chosen policy;
- remove gateway DNS entries from VLANs where gateway DNS is intentionally blocked;
- test UDP and TCP DNS, recursion, internal zones, failure behavior, and internet access from every
  VLAN before resuming the guest baseline.

The replacement `dns-core01` at `192.168.30.53` must be built beside the existing DNS guests.
Existing VMIDs 21001 and 21002 are retired only after the cutover is validated and soaked.

### High: forwarding policy is not explicitly fail-closed

The rule named `LAN to internet` matches `in-interface-list=LAN`, but the `LAN` interface list
contains only the bridge. Routed traffic enters through the VLAN interfaces, and the captured rule
counter is zero. The chain also has no final unconditional forward drop. Traffic not matching an
earlier rule can therefore reach RouterOS's implicit accept.

This makes the intended policy difficult to prove even where specific inter-VLAN drops exist.
Create an explicit internal-interface list or use the existing source address list, express every
approved path, and finish with a logged default drop. Stage this only through Safe Mode with a
wired management session and a tested rollback.

### High: DHCP ranges conflict with the future-state address contract

Every current pool uses `.100-.199`. The accepted policy now reserves `.1-.150` for static systems
and uses `.151-.254` for DHCP. Current leases in `.151-.199` can remain valid, but any static address
at `.151` or above conflicts with the future DHCP range. The managed monitoring guest currently uses
`.201` and must move to an admitted static address before the new pool is enabled.

The fresh lease inventory found seven active leases. Three currently use the future static range
(`192.168.30.108`, `192.168.30.116`, and `192.168.50.100`) and will move into `.151-.254` through
normal lease renewal. Four already use `.151-.254` and can remain. No current DHCP pool should be
changed until these clients, explicit reservations, and the static `.201` monitoring guest are
handled in the reviewed migration.

Do not change pools or the guest address in place without a lease inventory and a reviewed
migration plan. Existing leases and static assignments must be admitted into the desired model
before ranges move.

### High: router recovery exists only as an unproven configuration intention

`ether3` is configured as an untagged VLAN 20 management port, but it was inactive in the runtime
snapshot. Router Safe Mode, wired laptop access, current export, encrypted binary backup, off-router
copy, and rollback have not yet been recorded as a single proven recovery procedure. This is a hard
gate for issue #18 and for all live router changes.

### Medium: Wi-Fi state is asymmetric

The 5 GHz users, IoT, and guest interfaces were running, while its management virtual interface was
not. The 2.4 GHz base radio and its IoT/guest interfaces were inactive, while its management virtual
interface reported running. The explicit bridge VLAN entries also name different radio interfaces
than the runtime-managed entries.

Both radios and all four intended SSIDs need association, DHCP, DNS, internet, and isolation tests.
Do not infer health solely from configured objects.

### Medium: VLAN membership needs an explicit contract

VLANs 20, 30, 40, 70, and 90 are explicitly carried on the Proxmox trunk. VLANs 50 and 60 appear
only through dynamically managed Wi-Fi bridge entries and are not carried on `ether2`. This may be
intentional, but it must be declared and tested rather than left as an incidental result of Wi-Fi
datapaths.

### Medium: management rules and services overlap

An early rule accepts all remaining management-VLAN input, making the later narrow SSH/API rule
unreachable in the captured counters. WAN brute-force stages also have zero hits and overlap with
service address restrictions plus the WAN input drop. Plain API port 8728 is enabled on management,
while API TLS is disabled.

Reduce this to one documented management policy, prefer encrypted management protocols, and retain
only rules whose order and counters demonstrate their purpose.

### Accepted identity decision: router username is `admin`

The earlier collection attempted key authentication as the documented `homelab` account and was
rejected. The same key was accepted by `admin`. The 2026-07-21 user inventory confirms `admin` is
the only configured RouterOS user, and the owner has chosen to retain that username.

Keep its password only in `sops://credentials.router-admin.value`, retain key authentication, and
restrict SSH/Winbox to VLAN 20. Because discovery uses a full administrator, each collector command
must remain explicitly read-only and reviewable. A separate least-privilege audit user remains a
recommended later hardening improvement, not a prerequisite for the accepted design.

### Medium: disabled inbound NAT rules would not match the actual WAN interface

The disabled destination-NAT rules match physical `ether1`, while the WAN address is on
`VLAN10-WAN`. The current WAN address is also inside carrier-grade NAT space, so unsolicited public
inbound forwarding is not presently available without upstream changes or a tunnel. The rules are
disabled and pose no immediate exposure, but they should not be enabled as written.

### Medium: WireGuard is absent and NTP depends on DNS

No WireGuard configuration exists in the captured export even though remote recovery and management
are part of the future state. NTP uses DNS hostnames, so the current DNS failure can also prevent
clock synchronization and later cause TLS failures. DHCP does not advertise an NTP server.

### Low: configuration residue increases audit surface

Multiple optional RouterOS packages are installed without corresponding desired-state ownership.
IPv6 is disabled while a default IPv6 neighbor-discovery setting remains. These are not the current
outage, but unused packages and inert configuration should be reviewed after recovery and network
policy are stable.

## Safe reconciliation order

1. **Contain credentials:** rotate the exposed backup password and recapture secret-free evidence.
2. **Prove recovery:** connect a laptop to `ether3`, confirm VLAN 20 management, enter Safe Mode,
   save encrypted off-router backups, and rehearse rollback.
3. **Model exact current state:** include every port, VLAN, SSID, pool, lease exception, DNS target,
   firewall rule, NAT rule, service, package, scheduler, and time source.
4. **Validate DNS before mutation:** test both existing Technitium guests and router forwarding from
   each VLAN. Select one consistent per-VLAN DNS policy.
5. **Render a no-apply plan:** generate incremental RouterOS commands, inverse rollback commands,
   rule-order checks, and a per-VLAN acceptance matrix.
6. **Reconcile management and forwarding safety:** fix interface-list ownership, explicit approved
   paths, final drops, and encrypted management services without losing the wired session.
7. **Reconcile bridge and Wi-Fi:** prove both radios, each SSID, access ports, and intended trunk
   membership.
8. **Migrate DHCP/address ranges:** preserve live leases and static systems through a reviewed,
   non-disruptive transition.
9. **Add WireGuard and complete NTP/service hardening:** validate recovery access and time without
   broadening exposure.
10. **Run the complete matrix:** gateway, DHCP, DNS UDP/TCP, internet, isolation, management,
    rollback, and reboot persistence for every available VLAN.
11. **Resume the guest baseline:** only after VLAN 30 DNS and package connectivity pass independently.

No current guest, DNS server, storage service, or router policy should be retired automatically.
