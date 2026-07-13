# Proxmox LXC provisioning

## Outcome

Phase 3 turns each entry in `proxmox.containers` into one OpenTofu-owned, unprivileged Debian LXC.
The guest is placed on the configured Proxmox node, storage, bridge, and optional VLAN. It receives
the configured static management address, gateway, DNS servers, internal search domain, and one or
more SSH public keys.

The output map exposes each stable key, VM ID, hostname, node, management address, and initial
`root@address` SSH target. Issue #8 will consume that shape to build Ansible inventory and replace
the initial root bootstrap with the normal automation account and baseline configuration.

## Prerequisites

- The Proxmox API identity bootstrap has completed successfully.
- The selected Debian LXC template already exists on Proxmox.
- Every VM ID, hostname, and management address is unused.
- The address includes the management-network prefix and is not the gateway, network, or broadcast
  address.
- `automation.ssh_public_keys` contains at least one real OpenSSH public key.

Find the exact template filename on Proxmox before editing the site YAML. Template IDs use the form
`storage:vztmpl/filename`, for example
`local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst`.

## Configuration

Add the public bootstrap key and one or more containers to the ignored site file:

```yaml
proxmox:
  api_url: https://pve.home.arpa:8006
  node: pve
  storage: local-lvm
  token_id: homelab@pve!control-plane
  verify_tls: true
  containers:
    - key: dns-primary
      vm_id: 110
      hostname: dns-primary
      template_file_id: local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst
      address: 192.168.10.10/24
      cores: 2
      memory_mb: 1024
      swap_mb: 512
      disk_gb: 8
      started: true
      start_on_boot: true
      nesting: false
      protection: false
      tags:
        - dns
        - homelab

automation:
  ssh_user: automation
  ssh_private_key: ~/.ssh/homelab_ed25519
  ssh_public_keys:
    - ssh-ed25519 REPLACE_WITH_THE_REAL_PUBLIC_KEY automation
  become: true
```

`key` is the OpenTofu resource identity. Keep it unchanged when renaming or resizing a guest.
Reordering the list is safe. Changing a key declares one resource removed and another added.

`protection: true` asks Proxmox to block removal and some updates. Enable it only after acceptance;
turn it off deliberately before a planned destroy. `nesting` defaults to false and should be
enabled only for an application with a reviewed requirement.

## Plan and acceptance

Validate the YAML, then create a saved, non-destructive plan:

```bash
task config:validate
task tofu:check
```

Review the saved plan for the exact VM ID, template, storage, bridge/VLAN, address, sizing,
unprivileged mode, and resource count. The control panel intentionally has no apply button in
Phase 3. Live acceptance should use disposable IDs and addresses and prove create, in-place update,
and destroy from an explicitly reviewed saved plan before issue #6 is closed.

## Community Scripts boundary

Community Scripts can accelerate later application installation, but its host-side `ct/*.sh`
workflows also create and mutate LXCs. They must never run against an OpenTofu-owned guest. Issue
#14 tracks a curated, pinned application catalog that runs only after the guest exists, preferably
through a reviewed container-side installer invoked by Ansible. OpenTofu owns guest lifecycle;
Ansible owns baseline and application configuration.
