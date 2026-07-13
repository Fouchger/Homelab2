# Control panel design

## User experience

Run `task menu` to open the full-screen terminal control panel. The interface is suitable for a
local terminal, WSL2, or an SSH session to the Ubuntu control plane. It supports keyboard and mouse
input and adapts to common terminal sizes.

Navigation keys:

| Key | Destination |
|---|---|
| `1` | Overview |
| `2` | Configuration |
| `3` | Operations |
| `?` | Help and safety |
| `q` | Quit |

## Input management

The configuration editor loads the active YAML file or presents safe example values on first run.
Saving follows this sequence:

1. Trim and normalize user input.
2. Validate every field and all relationships between fields.
3. Reject unknown keys and unsupported schema versions.
4. Write a temporary file in the destination directory.
5. Flush the file to storage.
6. Atomically replace the previous configuration.

This lets the same automation operate different sites without changing application code.

## Non-interactive use

Every important menu capability also has a CLI command. CI, systemd services, and remote operators
must use these commands rather than attempting to automate keystrokes in the terminal UI.

Commands return `0` for success, `1` when readiness requirements are missing, and `2` for invalid
configuration or command usage.

## Adding an operation

Operations are registered in `src/homelabctl/operations.py`. Each operation has:

- a stable identifier;
- a user-facing title and description;
- an execution function returning a structured result;
- a destructive-action flag.

Infrastructure actions must not be registered until their underlying implementation, dry-run mode,
error handling, and tests exist. Destructive actions must show a plan and use the reusable
confirmation dialog.

**Check OpenTofu foundation** is intentionally non-destructive. It initializes only locked
providers, validates generated typed inputs, and writes a saved plan to the ignored `artifacts/`
directory. It never applies a plan. See [`OPENTOFU_STATE.md`](OPENTOFU_STATE.md).

## Secrets

The normal configuration object deliberately has no password or token-secret fields. Token IDs,
file paths, and public settings are safe to store, but actual secret material comes from the
SOPS/age runtime provider. It validates encrypted metadata before decrypting the document in
memory and prints only readiness status and provider names. See [`SECRETS.md`](SECRETS.md) for the
operator workflow.
