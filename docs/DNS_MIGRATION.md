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

## Immutable installation inputs

| Component | Version | Verification |
|---|---:|---|
| Technitium DNS | 15.4.0 | SHA-256 `461ac09d4304ace85093fc17b10a7ee13a8796eae0adb4393866bd4d66ab283f` |
| ASP.NET Core runtime | 10.0.10 | SHA-512 `4719249fcaca744b8edfa5b653366cabdd25f452a7cb9e961b8671ddd2f80eceef4bb8b74e0fad899f93e5c7c8b138890ff0bdb49f2daecb489455d9487a572b` |

The Technitium archive was downloaded from the official portable-release URL and its
`DnsServerApp.dll` reports version `15.4.0.0`. The service runs as the unprivileged `dns-server`
account with only `CAP_NET_BIND_SERVICE`. The default Technitium password is replaced immediately
through the documented local API with `credentials.technitium-admin.value`.

## Safe order

1. Capture DHCP leases and every static address. Move the managed `monitoring` guest from `.201`
   to an unused address at or below `.150` before changing a pool.
2. Provision `dns-core01` while DHCP and all clients still use `.30.2` and `.30.3`.
3. Install the pinned DNS adapter and change the default administrator password immediately.
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
