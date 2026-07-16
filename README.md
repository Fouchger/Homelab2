# Homelab Control Plane

A reusable, production-minded control plane for deploying and operating Proxmox homelabs.
It is designed for development from Windows 11 with WSL2 and execution from an Ubuntu 24.04
Proxmox LXC.

## Release status

Phases 1 through 4 are complete. `v0.4.0` adds accepted system configuration and guarded
operations to the Proxmox LXC and multi-domain Cloudflare DNS provisioning from `v0.3.0`.
Together with the secure-runtime foundations from `v0.1.0` and `v0.2.0`, the completed control
plane provides:

- a guided site configuration editor;
- strict validation and rejection of unknown settings;
- atomic YAML saves that cannot leave a partially written file;
- control-plane readiness checks;
- an effective-settings preview that never contains token secrets;
- keyboard and mouse navigation;
- a confirmation-dialog foundation for future destructive operations;
- both interactive and unattended command-line operation.
- deterministic unprivileged Debian LXC lifecycle management on the configured bridge and VLAN;
- explicit multi-zone Cloudflare A, AAAA, and CNAME ownership;
- credential-aware application of only an explicitly reviewed saved OpenTofu plan;
- OpenTofu-derived Ansible inventory, a Debian-family guest baseline, and guarded confirmation
  workflows; and
- a checksum-pinned Uptime Kuma pilot with dedicated-account execution, health checks, and
  repeatable application apply operations.

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for acceptance evidence and deferred follow-up work, and
[`CHANGELOG.md`](CHANGELOG.md) for release history.

## Quick start

Run the installer:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Fouchger/Homelab2/main/install.sh)"
```

The installer supports Debian, Ubuntu, and Ubuntu on WSL2. It installs the minimum system
packages plus [uv](https://docs.astral.sh/uv/) and [Task](https://taskfile.dev/), then clones the
repository to `~/Homelab2`. Continue with:

```bash
cd ~/Homelab2
task setup
task config:init
task menu
```

Set `HOMELAB_INSTALL_DIR` to use a different destination:

```bash
HOMELAB_INSTALL_DIR=~/control-plane bash -c "$(curl -fsSL https://raw.githubusercontent.com/Fouchger/Homelab2/main/install.sh)"
```

The default configuration path is `config/sites/local.yaml`. It is intentionally ignored by Git.
Use a different file without changing code:

```bash
task menu CONFIG=config/sites/lab-a.yaml
```

You can also use the CLI directly:

```bash
uv run homelabctl validate --config config/sites/local.yaml
uv run homelabctl doctor --config config/sites/local.yaml
uv run homelabctl show --config config/sites/local.yaml
```

The preferred operator workflow is the control-panel menu:

```bash
task menu
```

Its purpose-based Setup and Proxmox sections initialize encrypted secrets, prepare the dedicated
Proxmox SSH public key, install it with an interactive `ssh-copy-id` dialog, and perform the
plan/confirm/apply API identity bootstrap. Infrastructure creates and configures the dedicated
guest-automation SSH key and contains the safe OpenTofu foundation check, while Maintenance
contains guarded code updates. Each section shares a session activity
history with a portable plain-text copy view for support. It supports native terminal selection,
an optional direct clipboard request, and an exported `logs/activity-report.txt` fallback. CLI and
Task commands remain available for unattended operation and recovery. See
[`docs/SECRETS.md`](docs/SECRETS.md) for identity backup, recovery, and rotation, and
[`docs/OPENTOFU_STATE.md`](docs/OPENTOFU_STATE.md) for provider and state operations. Phase 3
resource contracts are documented in
[`docs/PROXMOX_PROVISIONING.md`](docs/PROXMOX_PROVISIONING.md) and
[`docs/CLOUDFLARE_DNS.md`](docs/CLOUDFLARE_DNS.md).
The curated in-guest application boundary and Uptime Kuma pilot are documented in
[`docs/APPLICATIONS.md`](docs/APPLICATIONS.md).

Once installed, future code upgrades are available through **Maintenance → Update control plane**.
The updater previews GitHub changes, accepts only a clean fast-forward, preserves ignored runtime
data, synchronizes locked dependencies, and asks the operator to restart the menu.

## Configuration policy

- Reusable defaults and examples are committed.
- User-specific site files are created under `config/sites/` and ignored.
- `site.domain` is the internal DNS suffix; `cloudflare.domains` accepts zero, one, or many
  external domains.
- `proxmox.containers` and `cloudflare.records` default to empty, so existing Phase 2
  configurations remain valid.
- Guests and public records have stable keys; reordering YAML does not replace resources.
- Passwords and token secrets are never part of the general site model.
- Proxmox and Cloudflare token secrets are loaded from SOPS/age-encrypted YAML only at runtime.
- The age identity is stored outside the repository and must have an offline encrypted backup.
- OpenTofu state, plan files, runtime logs, and generated artifacts are ignored.

The configuration structure is documented in
[`config/examples/site.yaml`](config/examples/site.yaml). The generated JSON Schema is stored at
`config/schema/site.schema.json`.

## Common tasks

```text
task                   Open the control panel
task configure         Open the guided configuration editor
task config:validate   Validate site configuration
task config:show       Show effective non-secret settings
task doctor            Check local readiness
task secrets:init      Initialize encrypted credential placeholders
task secrets:edit      Edit credentials through SOPS
task secrets:check     Decrypt and validate without displaying values
task proxmox:bootstrap:plan  Preview API identity changes
task proxmox:bootstrap       Create/reconcile the API user, role, ACL, and token
task infrastructure:ssh-key Create and configure the guest automation SSH key
task tofu:check              Validate typed inputs and create a non-destructive plan
task tofu:apply              Apply only the existing reviewed plan with runtime credentials
task ansible:inventory       Derive ignored runtime inventory from OpenTofu outputs
task ansible:setup:plan      Preview installation of Ansible prerequisites
task ansible:setup           Install Ansible and locked collections
task ansible:check           Preview the Debian-family guest baseline
task ansible:apply           Apply the reviewed guest baseline
task applications:plan      Show curated application revisions and checksums
task applications:check     Preview curated application changes
task applications:apply     Apply and health-check curated applications
task check             Run formatting, linting, tests, and config validation
```

See [`docs/CONTROL_PANEL.md`](docs/CONTROL_PANEL.md) for operation and extension guidance and
[`docs/PROXMOX_BOOTSTRAP.md`](docs/PROXMOX_BOOTSTRAP.md) for the administrator bootstrap boundary.

## Security boundary

The control plane should run in an unprivileged LXC. Use a dedicated Proxmox API token and a
dedicated SSH automation account with the minimum permissions needed. Do not commit `.env` files,
private keys, OpenTofu state, or decrypted secrets.

## License

GPL-3.0-only. See [`LICENSE`](LICENSE).
