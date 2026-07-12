# Proxmox API identity bootstrap

The control plane bootstraps its own Proxmox API identity once, before OpenTofu is allowed to
provision resources. This is the only Phase 2 operation that needs an existing Proxmox
administrator connection.

## Security model

The bootstrap creates or reconciles:

- the user from `proxmox.token_id`, such as `homelab@pve`;
- a custom `HomelabProvisioner` role;
- a propagating ACL for that role at `/`;
- the named token, such as `control-plane`, with privilege separation enabled;
- an equivalent ACL for the separated token.

Proxmox defines a separated token's effective permissions as the intersection of its own ACLs and
the backing user's ACLs. The workflow therefore assigns the same narrow role to both subjects. It
does not grant `Administrator`, `Permissions.Modify`, `Sys.Modify`, realm management, or user
management privileges.

The initial role supports the first planned VM/LXC resource profile. Any privilege required by a
later OpenTofu resource must be reviewed and added explicitly with that resource; the broad example
role from the provider documentation is not copied wholesale.

## Connection from the control plane

The code remains on the control-plane LXC. It opens a non-interactive SSH connection to the
hostname in `proxmox.api_url`, streams a protected Bash program to that host, and runs `pveum`
there as root. Only progress and the one-time token creation response cross the SSH connection.

The privilege list is transported as a comma-delimited SSH argument and converted back to the
space-delimited format expected by `pveum --privs` on the Proxmox host. If a remote command fails,
the activity log shows redacted, step-specific SSH/`pveum` diagnostics; token creation output is
never included in an error.

There is one unavoidable initial trust step. In the menu:

1. Open **Operations**.
2. Run **Prepare Proxmox SSH access** and confirm its plan.
3. In the separate key-install dialog, choose **Install key automatically**.
4. The control panel temporarily suspends and runs `ssh-copy-id`; enter the current Proxmox root
   password directly at the SSH prompt.
5. When the menu returns, run **Bootstrap Proxmox API identity**.

The root password is handled only by `ssh-copy-id` and is never returned to or stored by the control
plane. The dialog also provides **Copy command** for running the same command in another
control-plane terminal.

If Proxmox is configured to reject root password SSH, use **Copy console fallback** and run that
one-line command in the Proxmox web shell or physical console instead.

The private key remains at `~/.ssh/proxmox_bootstrap_ed25519` on the control plane and is never
displayed. Password prompting is enabled only inside the interactive `ssh-copy-id` installation;
the actual API bootstrap requires the key and disables SSH password authentication. The first host
key is accepted using SSH trust on first use; a later changed host key is rejected.

## Menu plan and apply

Clicking **Bootstrap Proxmox API identity** first shows the SSH target, key, role, ACL scope,
privileges, token behavior, SOPS handoff, and API verification. Nothing changes until the
confirmation dialog is accepted.

The Task and CLI forms below are fallback interfaces for unattended operation, troubleshooting,
and tests—not the normal user workflow.

Ensure administrator SSH authentication works without putting a password in a command:

```bash
ssh root@pve.home.arpa true
```

Preview the exact identity, ACL, token behavior, and privilege list:

```bash
task proxmox:bootstrap:plan
```

Apply that plan:

```bash
task proxmox:bootstrap
```

The host defaults to `root@` plus the hostname from `proxmox.api_url`. Use the CLI directly when a
different administrator SSH target is required:

```bash
uv run homelabctl proxmox bootstrap \
  --config config/sites/local.yaml \
  --secrets config/secrets/local.enc.yaml \
  --ssh-target admin@pve.home.arpa \
  --apply
```

The remote script sends progress to its protected SSH error stream and returns the token creation
JSON only to the local process. The one-time value is passed to `sops set --value-stdin`; it is never
placed in a command argument, general configuration, or a plaintext file. The workflow then calls
the authenticated Proxmox `/api2/json/version` endpoint before reporting success.

Every apply also appends detailed troubleshooting information to
`logs/proxmox-bootstrap.log`. The menu displays the absolute path after an operation. The log
includes remote `pveum` progress, SSH exit status, API endpoint, TLS mode, HTTP status/reason, and
sanitized error responses. Token creation output, authorization values, UUID-shaped secrets, and
JSON token values are redacted or suppressed. On Linux the log is restricted to the current user;
the `logs/` directory is excluded from Git.

API verification honors **Verify TLS certificate** from the Configuration page. Keep it enabled
when the control plane trusts the Proxmox certificate authority and the API URL uses a hostname on
the certificate. For a private self-signed endpoint, either install that CA on the control plane or
deliberately disable the switch; bootstrap never weakens certificate verification automatically.

## Safe reruns and rotation

Normal reruns reconcile the role privileges, enabled user, user ACL, token ACL, and permission
calculation. An existing token is never replaced silently. Its stored SOPS value must match the
configured token ID and authenticate successfully.

If the role, user, and token exist but SOPS still contains the generated placeholder, the menu
shows a separate recovery confirmation. Accepting it deletes only the named token, creates its
replacement with the same separated ACL, sends the new one-time value directly to SOPS, and verifies
API authentication. Cancelling retains the existing token unchanged. SOPS decryption failures do
not offer rotation; age access must be repaired first so a newly issued value cannot be lost.

If the token exists but its one-time value was lost, repair the SOPS and SSH prerequisites, review
the menu recovery confirmation or rotate explicitly through the CLI:

```bash
uv run homelabctl proxmox bootstrap \
  --config config/sites/local.yaml \
  --secrets config/secrets/local.enc.yaml \
  --rotate-token

uv run homelabctl proxmox bootstrap \
  --config config/sites/local.yaml \
  --secrets config/secrets/local.enc.yaml \
  --rotate-token \
  --apply
```

Rotation deletes only the named token after the explicit apply flag, creates its replacement,
updates SOPS, and verifies the replacement. It does not delete the user or role.

See the official [Proxmox user-management documentation](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#pveum_authentication_realm)
and the [bpg/proxmox provider documentation](https://registry.terraform.io/providers/bpg/proxmox/latest/docs)
for the underlying token and provider behavior.
