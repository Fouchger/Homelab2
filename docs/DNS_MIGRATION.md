# DNS replacement and address migration

## Accepted decisions

- Router administrator username: `admin`.
- Router password: existing value retained only through
  `sops://credentials.router-admin.value`; plaintext is never rendered.
- Replacement DNS: `dns-core01`, Proxmox VMID 220, `192.168.30.53/24`, VLAN 30.
- DNS software: Technitium DNS Server 15.4.0 on ASP.NET Core 10.0.10.
- Static and reserved addresses: `.1-.150` on every internal `/24`.
- DHCP: `.151-.254` on every internal `/24`.
- Existing DNS guests VMID 21001 (`192.168.30.2`) and VMID 21002 (`192.168.30.3`) are retired
  after cutover, not before it.

Passwords are deliberately not copied from the router or old DNS guests. Router, Technitium, and
each Wi-Fi network use distinct encrypted SOPS keys. The Technitium adapter receives its password
only through the child process environment and marks all password API tasks `no_log`.

## Pinned helper installation

| Component | Pin | Verification |
|---|---:|---|
| Community Scripts repository | `1cfddc4c9c28243c455a20fab3ef5d423ffc9d80` | Exact Git revision |
| `ct/technitiumdns.sh` | same revision | SHA-256 `56e839cf340f5b7a99c4967b8dbbd9231187a9c72c1e5d8408f145c30ddc2b08` |
| `misc/build.func` | same revision | SHA-256 `40b85ff7dd7705b5464d012c4c79596ae689af695d99a27bfe07303641ad1f8a` |
| Technitium DNS | 15.4.0 | Verified inside the LXC after helper installation |

The helper entry normally downloads supporting files from its moving `main` branch. Homelab2
downloads the pinned entry and build helper, verifies both hashes, and rewrites every transitive
Community Scripts URL to the same immutable revision before execution. It refuses an occupied VMID
whose hostname, address, or VLAN differs. The default Technitium password is then replaced
immediately through the documented local API with `credentials.technitium-admin.value`.

The configuration adapter restricts recursion to the seven internal VLANs, uses DNS-over-TLS
forwarders, enables DNSSEC validation and QNAME minimization, creates forward and reverse
`home.arpa` records, and installs a host firewall. DHCP remains exclusively on RouterOS.

Preview and provision with the active DNS site configuration:

```text
task dns:provision:plan CONFIG=config/examples/dns-core-site.yaml
task dns:provision CONFIG=config/examples/dns-core-site.yaml
task applications:apply CONFIG=config/examples/dns-core-site.yaml
```

## Safe order

1. Capture DHCP leases and every static address. Move the managed `monitoring` guest from `.201`
   to an unused address at or below `.150` before changing a pool.
2. Provision `dns-core01` through the pinned Community Scripts workflow while DHCP and all clients
   still use `.30.2` and `.30.3`.
3. Apply the DNS configuration adapter and change the default administrator password immediately.
4. Export both old Technitium configurations. Import required zones, forwarders, block lists, and
   records into `.30.53`; do not import unknown users or stale API tokens blindly.
5. Validate recursion, DNSSEC, internal `home.arpa`, UDP/TCP 53, caching, time sync, reboot, and
   backup/restore directly against `.30.53` from every VLAN.
6. Change static clients and RouterOS DHCP network entries to advertise only `.30.53`. Shorten the
   old DHCP lease time before cutover, then wait for renewal.
7. Observe query traffic on `.30.2` and `.30.3` until expected clients have moved. Keep both old
   guests powered on but remove them from client configuration.
8. After the soak and rollback window, back up and shut down VMIDs 21001 and 21002. Delete them only
   with separate confirmation after their backups have passed a restore test.
9. Change each RouterOS DHCP pool to `.151-.254` only after admitted static addresses and current
   leases prove that range is safe.

The replacement is initially a single DNS server, as requested. Retiring both old servers removes
DNS redundancy; a later `dns-core02` at `.30.54` is recommended before DNS becomes a hard dependency
for additional production services.

The transitional `dns-core-site.yaml` deliberately keeps the existing OpenTofu-owned monitoring
guest in its container list. Removing it from the input would create an unsafe destroy proposal.
Its `.201` address remains temporarily until a separate reviewed readdressing step.
