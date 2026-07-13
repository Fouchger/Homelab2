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
| `3` | Setup |
| `4` | Proxmox |
| `5` | Infrastructure |
| `6` | Maintenance |
| `7` | Diagnostics |
| `c` | Open the activity copy view |
| `?` | Help and safety |
| `q` | Quit |

Actions are grouped by purpose instead of appearing in one large Operations page. Setup contains
configuration and credential preparation, Proxmox contains administrator bootstrap actions,
Infrastructure contains OpenTofu checks, Maintenance contains control-plane updates, and
Diagnostics contains readiness and effective-setting reports. Each section presents its actions
as sub-actions and shares the same session activity history.

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
- a section that determines its menu location;
- an execution function returning a structured result;
- a destructive-action flag.

Infrastructure actions must not be registered until their underlying implementation, dry-run mode,
error handling, and tests exist. Destructive actions must show a plan and use the reusable
confirmation dialog.

**Prepare guest automation SSH key** creates the configured Ed25519 identity only when both key
files are absent. It verifies an existing pair and its SHA-256 fingerprint, refuses incomplete or
mismatched pairs, applies restrictive file permissions, and adds the public-key path to the site
configuration. Private key material is never displayed or logged.

**Check OpenTofu foundation** is intentionally non-destructive. It initializes only locked
providers, validates generated typed inputs, and writes a saved plan to the ignored `artifacts/`
directory. It never applies a plan. See [`OPENTOFU_STATE.md`](OPENTOFU_STATE.md).

Action sections scroll when needed, so no implemented menu action is clipped. Secret-entry actions
use masked dialogs and pass values directly to their encrypted operation without writing them to
the activity log. Every action section has **View / copy activity**, which opens the complete
session history as plain text for support and debugging; terminal colour markup is omitted.

Remote sessions cannot always write to the operator's local clipboard because MobaXterm and browser
terminals may block OSC 52 clipboard requests. The activity dialog therefore offers three paths:

1. **Open terminal copy view** temporarily shows the transcript in a normal terminal so the client
   can select and copy it using its own controls.
2. **Try direct clipboard** requests OSC 52 clipboard transfer when the terminal permits it.
3. A sanitized fallback is always written to `logs/activity-report.txt` for access through SFTP or
   a text editor.

**Update control plane** fetches the configured GitHub branch, displays the commits and changed
files, and requires confirmation before a fast-forward-only merge. It refuses tracked source edits
and never resets, stashes, or deletes files. Ignored runtime configuration, encrypted secrets,
OpenTofu state, logs, caches, and age keys remain in place. Restart the menu after a successful
update so the running process loads the new code.

Cloudflare and Proxmox credentials are validated independently during guided setup. A generated
placeholder for a provider that has not been configured yet therefore does not block saving and
validating the other provider.

## Secrets

The normal configuration object deliberately has no password or token-secret fields. Token IDs,
file paths, and public settings are safe to store, but actual secret material comes from the
SOPS/age runtime provider. It validates encrypted metadata before decrypting the document in
memory and prints only readiness status and provider names. See [`SECRETS.md`](SECRETS.md) for the
operator workflow.
