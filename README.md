# Homelab Control Plane

A reusable, production-minded control plane for deploying and operating Proxmox homelabs.
It is designed for development from Windows 11 with WSL2 and execution from an Ubuntu 24.04
Proxmox LXC.

## Current milestone

The first milestone provides a professional terminal control panel with:

- a guided site configuration editor;
- strict validation and rejection of unknown settings;
- atomic YAML saves that cannot leave a partially written file;
- control-plane readiness checks;
- an effective-settings preview that never contains token secrets;
- keyboard and mouse navigation;
- a confirmation-dialog foundation for future destructive operations;
- both interactive and unattended command-line operation.

OpenTofu provisioning and Ansible deployment actions will be added step by step. The menu only
shows operations that are actually implemented.

## Quick start

Run the installer:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Fouchger/Homelab2/main/install.sh)"
```

Prerequisites are [uv](https://docs.astral.sh/uv/) and
[Task](https://taskfile.dev/). From WSL2 or Ubuntu:

```bash
task setup
task config:init
task menu
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

## Configuration policy

- Reusable defaults and examples are committed.
- User-specific site files are created under `config/sites/` and ignored.
- Passwords and token secrets are never part of the general site model.
- The Proxmox token secret is currently supplied using `PROXMOX_VE_API_TOKEN`.
- SOPS and age encrypted secret files will be added in the secrets milestone.
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
task check             Run formatting, linting, tests, and config validation
```

See [`docs/CONTROL_PANEL.md`](docs/CONTROL_PANEL.md) for operation and extension guidance.

## Security boundary

The control plane should run in an unprivileged LXC. Use a dedicated Proxmox API token and a
dedicated SSH automation account with the minimum permissions needed. Do not commit `.env` files,
private keys, OpenTofu state, or decrypted secrets.

## License

GPL-3.0-only. See [`LICENSE`](LICENSE).
