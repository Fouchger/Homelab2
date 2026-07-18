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
- `automation.ssh_public_key_files` references at least one real OpenSSH public-key file, or
  `automation.ssh_public_keys` contains an inline public key.

Find the exact template filename on Proxmox before editing the site YAML. Template IDs use the form
`storage:vztmpl/filename`, for example
`local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst`.

From the control panel, open **Infrastructure** and run **Prepare guest automation SSH key**. After
reviewing its plan, confirm once. The action:

- creates `~/.ssh/homelab_ed25519` and `~/.ssh/homelab_ed25519.pub` when both are absent;
- verifies and preserves an existing complete pair;
- refuses incomplete, mismatched, or passphrase-dependent automation keys;
- reports only the public SHA-256 fingerprint;
- adds `~/.ssh/homelab_ed25519.pub` to `automation.ssh_public_key_files`.

The unattended equivalent is:

```bash
task infrastructure:ssh-key CONFIG=config/sites/local.yaml
```

Do not reuse `proxmox_bootstrap_ed25519`: that key authorizes privileged access to the Proxmox
host and should retain its narrower bootstrap purpose.

## Configuration

The key action maintains the automation section. Add one or more containers to the ignored site
file:

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
  ssh_public_keys: []
  ssh_public_key_files:
    - ~/.ssh/homelab_ed25519.pub
  become: true
```

The site file stores only the public-key path. During planning, the control plane reads that file,
validates its single OpenSSH key, and passes the public key text to OpenTofu. The private key is
never placed in generated OpenTofu variables.

`key` is the OpenTofu resource identity. Keep it unchanged when renaming or resizing a guest.
Reordering the list is safe. Changing a key declares one resource removed and another added.

`protection: true` asks Proxmox to block removal and some updates. Enable it only after acceptance;
turn it off deliberately before a planned destroy. `nesting` defaults to false and should be
enabled only for an application with a reviewed requirement.

Debian 13 templates use systemd 257, which can start an LXC in a degraded state when nesting is
disabled (for example, failed `dev-mqueue.mount`, `run-lock.mount`, and `tmp.mount`). If those
failures occur, set `nesting: true` and verify the guest after replacement or restart. Keep the
container unprivileged and do not also enable keyctl, arbitrary mount types, privileged mode, or an
unconfined AppArmor profile without a separate requirement. Nesting exposes some host procfs and
sysfs information to the guest, so it remains an explicit per-container security decision.

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
Apply only that saved plan through `task tofu:apply`, which supplies runtime provider credentials
without storing them in the plan or configuration.

## Community Scripts boundary

Community Scripts can accelerate later application installation, but its host-side `ct/*.sh`
workflows also create and mutate LXCs. They must never run against an OpenTofu-owned guest. Issue
#14 tracks a curated, pinned application catalog that runs only after the guest exists, preferably
through a reviewed container-side installer invoked by Ansible. OpenTofu owns guest lifecycle;
Ansible owns baseline and application configuration.

That rule describes the accepted Phase 3 and Phase 4 resource path. Phase 7 may use a separately
reviewed, commit-pinned Community Scripts creator for a brand-new, collision-checked replacement.
The resulting guest must be captured and imported into matching OpenTofu configuration, followed
by a zero-change plan, before it is accepted as managed. Community Scripts never runs against an
already managed or discovered legacy guest, and a failed new guest is not automatically deleted.
See [`ROADMAP.md`](ROADMAP.md).
