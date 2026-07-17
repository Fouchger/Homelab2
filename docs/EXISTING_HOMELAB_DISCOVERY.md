# Existing homelab discovery

Homelab2 can adopt an existing MikroTik and Proxmox installation without resetting either one.
Discovery is read-only: it records the current topology so that the desired model can reproduce
the live design before any managed change is proposed.

## Safety boundary

- Do not reset the router or reinstall Proxmox during discovery.
- Keep the Windows laptop connected to a known management port or SSID.
- Do not apply an old RouterOS export to the live router.
- Never attach a RouterOS export created with `show-sensitive=yes`.
- Review discovery output before sharing it. Redacted output still contains operational details
  such as addresses, hostnames, interfaces, public addresses, and hardware information.
- The discovery folder is ignored by Git and must remain outside source control.

RouterOS hides sensitive values in a normal export. The collector uses the normal `/export`
command without `show-sensitive` and performs an additional local redaction pass. This provides
useful defence in depth, but operator review remains required. The current collector redacts
quoted multiline values and fails closed if a secret-shaped assignment survives. Snapshots made
with an older collector must not be shared merely because their filename contains `redacted`;
rerun the current collector and review the new output.

## Prerequisites

From the Windows laptop:

1. Confirm the Windows OpenSSH client is installed: `ssh -V`.
2. Confirm SSH access to the MikroTik using a read-only account where possible.
3. Confirm SSH access to the Proxmox host. Root provides the most complete read-only inventory;
   an audit account can be used if it has permission to run the listed inspection commands.
4. Run PowerShell from the repository root.

## Collect the current state

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\other_scripts\discovery\collect-existing-homelab.ps1 `
    -RouterHost 192.168.20.1 `
    -RouterUser homelab `
    -RouterIdentityFile "$env:USERPROFILE\.ssh\homelab_router_ed25519" `
    -ProxmoxHost 192.168.20.10 `
    -ProxmoxUser root `
    -AllowInteractiveAuthentication
```

Change the addresses and usernames to match the live environment. SSH key authentication is
preferred. `-AllowInteractiveAuthentication` lets OpenSSH prompt when a key is not installed; the
collector does not receive or store the password. Omit the switch once key authentication works.
Use `-ProxmoxIdentityFile` in the same way when the Proxmox key is not selected by SSH config.

Output is written below `discovery-output/<timestamp>/` and contains:

- the Windows laptop network view;
- a secret-free RouterOS configuration export;
- selected dynamic MikroTik interface, route, DHCP, DNS, and firewall state; and
- Proxmox version, networking, storage, guest inventory, sanitized guest definitions, and failed
  service state.

Failed SSH collection is recorded in the corresponding output file without changing the target.

## Create local read-only evidence

After a successful collection, run admission checks without reconnecting to either device:

```powershell
uv run homelabctl discovery evidence `
    --manifest config/examples/future-state.yaml `
    --proxmox-snapshot discovery-output/<timestamp>/proxmox-redacted.txt `
    --router-snapshot discovery-output/<timestamp>/mikrotik-runtime-redacted.txt `
    --output artifacts/discovery-admission.json
```

The evidence contains hashes and counts only. Exact VMIDs, addresses, MACs, disk serials, SSIDs,
hostnames, and secret values are not written to the evidence file. `artifacts/` remains ignored.

## Adoption sequence

After discovery:

1. Draw the observed physical ports, trunks, VLANs, addresses, DHCP scopes, DNS servers, firewall
   paths, Proxmox storage, and guests.
2. Identify contradictions and unmanaged resources without changing them.
3. Encode the observed state in the Homelab2 site model.
4. Render a proposed configuration and compare it with the redacted live export.
5. Back up the router and Proxmox guests independently.
6. Adopt one layer at a time, beginning with validation-only operations.
7. Require a tested rollback and direct laptop access before every network change.

The first managed render must aim for zero functional change. Improvements are proposed only after
the live state has been represented accurately and verified.
