# MikroTik complete desired state

This Phase 07.5 contract describes the complete hAP ax2 network, not only the VLAN involved in the
current DNS failure. It is a review artifact and does not connect to or change the router.

## RouterOS baseline

The captured router runs RouterOS 7.23.2. MikroTik's stable changelog lists 7.23.2, released
2026-07-06, as the current stable release checked on 2026-07-21. The desired state therefore pins
both `validated_version` and `minimum_version` to 7.23.2 and does not propose an upgrade.

The configuration choices follow current official RouterOS guidance:

- bridge VLAN filtering declares physical access/trunk membership explicitly and retains a wired
  VLAN 20 recovery port;
- the router does not provide recursive DNS to clients during the transition, so firewall input
  does not need to expose TCP/UDP 53;
- input and forwarding policy are stateful and end in explicit logged drops;
- source NAT uses the WAN interface list rather than physical `ether1`, because the WAN client is
  attached to VLAN 10;
- unused HTTP and API services are disabled, and Winbox/SSH remain management-VLAN only;
- Wi-Fi VLAN assignments cover both 2.4 GHz and 5 GHz, but security material remains in SOPS;
- Safe Mode and tested recovery are hard gates before any live bridge, VLAN, or firewall change.

Official references:

- [RouterOS stable changelog](https://mikrotik.com/download/changelogs?channelFilter=stable)
- [Bridge VLAN filtering](https://manual.mikrotik.com/docs/bridging-and-switching/)
- [DNS](https://manual.mikrotik.com/docs/network-management/dns/)
- [Firewall](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/firewall/)
- [Packet flow](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/packet-flow-in-routeros/)
- [WiFi](https://help.mikrotik.com/docs/spaces/ROS/pages/224559120/WiFi)
- [Securing the router](https://manual.mikrotik.com/docs/getting-started/securing-your-router/)
- [Safe Mode](https://help.mikrotik.com/docs/spaces/ROS/pages/328155/Configuration%20Management)

## Infrastructure included

| Area | Desired policy |
|---|---|
| WAN | VLAN 10 on `ether1`, DHCP/CGNAT, no inbound port forwards |
| Physical ports | `ether2` trunk; `ether3` wired VLAN 20 recovery; `ether4/5` trusted users |
| Internal networks | VLANs 20, 30, 40, 50, 60, 70, and 90 with `.1` gateways |
| Wi-Fi | Users, IoT, and guest SSIDs on both bands; management SSID disabled by default |
| DNS | Final clients use `dns-core01` at `.30.53` directly; router cache disabled |
| DHCP | `.151-.254` after lease admission; `.1-.150` remains static/reserved |
| Firewall | Explicit approved paths, management only from VLAN 20, final logged drops |
| NAT | Outbound masquerade through the WAN interface list |
| Services | Winbox/SSH management only; API and web management disabled |
| Identity | Existing `admin` username retained; SSH key plus distinct SOPS-backed password |
| Time | Two DNS-based NTP sources, tested only after direct DNS is healthy |
| WireGuard | Pending until endpoint, peers, and encrypted keys are approved |

VLANs 50 and 60 remain Wi-Fi-only in the desired physical-port contract. They are deliberately not
added to the Proxmox trunk until a wired workload requires them. That makes their absence from the
trunk intentional rather than incidental.

## Transitional DNS decision

During construction, clients continue using the existing Technitium addresses `.30.2` and `.30.3`.
The replacement `dns-core01` at `192.168.30.53` is built and tested beside them. DHCP and static
guest configuration then switch directly to `.30.53`; a VLAN gateway must not be advertised as DNS
while `allow-remote-requests` is off. Existing VMIDs 21001 and 21002 are retired only after lease
renewal, UDP/TCP validation from every VLAN, a soak period, and a tested rollback.

DNS acceptance requires UDP and TCP port 53 tests, internal-zone resolution, internet recursion,
single-server failure, and complete failure behaviour from every VLAN.

## Review workflow

Validate the model:

```text
homelabctl mikrotik validate --file config/examples/mikrotik-desired.yaml
```

Render the review files:

```text
homelabctl mikrotik render --file config/examples/mikrotik-desired.yaml --output artifacts/mikrotik-proposal
```

The output contains a JSON scope and gate report, a per-VLAN acceptance matrix, and a candidate
RouterOS script. The script begins with `:error`, so importing it stops before the first candidate
command. It is not a ready-to-apply reconciliation script. A fresh live export must first be diffed
to convert candidate additions into ordered `set`, `add`, `disable`, and rollback operations.

## Live-change gates

The fresh secret-free export gate is complete. The other recovery gates remain false and may be
marked complete only when evidence exists for credential rotation, encrypted off-router backup,
wired VLAN 20 management, Safe Mode rehearsal, and rollback rehearsal. Even after all flags are
true, this phase has no apply command; live execution requires a separately reviewed implementation.
