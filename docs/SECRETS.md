# Encrypted secret operations

The control plane stores machine credentials in SOPS-encrypted YAML and uses an age identity to
decrypt them only when an operation needs them. Token values do not belong in the site YAML,
`.env` files, shell history, logs, or command arguments.

## Menu workflow

The normal workflow requires no secret-management commands. Open `task menu`, select Operations,
and run **Initialize encrypted secrets**. The menu presents a plan and confirmation, then:

- creates the dedicated age identity when it does not exist;
- derives and displays only its public recipient;
- creates the repository SOPS policy when absent;
- creates an encrypted Proxmox token placeholder without a plaintext credential file.

The **Bootstrap Proxmox API identity** menu action also ensures this secret store exists, so it is
safe to go directly to that operation. Back up a newly created age identity offline before relying
on it for recovery.

When external domains are configured, run **Set Cloudflare API token** from Operations. After a
confirmation, the menu opens a masked token field and passes the value directly to SOPS through
protected standard input. The token is never displayed, logged, placed in a command argument, or
written to a plaintext file. The menu then decrypts and validates the complete credential structure
before reporting success.

## CLI fallback

The installer provides `sops`, `age`, and `age-keygen`. For unattended recovery or development,
the equivalent commands are:

```bash
mkdir -p ~/.config/sops/age
chmod 700 ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
age-keygen -y ~/.config/sops/age/keys.txt
task secrets:init AGE_RECIPIENT=age1replace_with_your_public_recipient
task secrets:edit
task secrets:check
```

`secrets:init` encrypts placeholders in memory and writes `config/secrets/local.enc.yaml`. The
local file is ignored by Git by default. It also creates `.sops.yaml` when no recipient policy is
present. `secrets:edit` opens the protected SOPS editor; replace both placeholders with real token
values. `secrets:check` decrypts and validates the structure but prints only provider names and the
encrypted file path.

Initialization creates this decrypted structure:

```yaml
schema_version: 1
proxmox:
  api_token: token-secret-created-by-proxmox
```

Add Cloudflare only when external domains are configured:

```yaml
cloudflare:
  api_token: scoped-cloudflare-token
```

Cloudflare is optional when `cloudflare.domains` is empty. Proxmox is always required. The
encrypted document retains the clear YAML keys but every `api_token` value must be an `ENC[...]`
SOPS value. The loader refuses a document with missing SOPS metadata or a plaintext token.

Readiness fails when a credential required by the active configuration is missing. Either use the
guided Cloudflare token operation or remove the external domains from Configuration when
Cloudflare management is not wanted.

Use `HOMELAB_SECRETS` or `SECRETS=` with Task to select another encrypted file.

## Backup and recovery

The age identity is the recovery key. Losing every copy makes the encrypted secrets unrecoverable.
Keep at least one offline, encrypted backup separate from the control-plane container. A password
manager may hold a recovery copy, but it is not a runtime dependency.

Test recovery before relying on the backup:

1. Restore `keys.txt` into a temporary account or isolated system.
2. Set `SOPS_AGE_KEY_FILE` to that restored file.
3. Run `task secrets:check`.
4. Remove the temporary restored identity securely.

Never commit an age identity or place it directly in `SOPS_AGE_KEY`. Prefer the protected identity
file and `SOPS_AGE_KEY_FILE` when overriding its location.

## Stable credentials across rebuilds

Phase 6 separates account identity from secret material:

- stable usernames and service-account names live in the versioned site manifest;
- every service has a unique password, API token, SSH key, or database credential;
- accepted secret values live in a SOPS-encrypted production YAML bundle;
- a rebuild decrypts and reuses those accepted values instead of generating unrelated credentials;
- no universal password is shared across the homelab; and
- rotation updates the encrypted bundle before the previous credential is revoked.

The encrypted production bundle may be committed to GitHub after its SOPS metadata and encrypted
values have been validated. The age private identity, private SSH keys, plaintext passwords,
recovery codes, decrypted `.env` files, and generated runtime secret files must never be committed.
Runtime files are rendered with restrictive permissions and are excluded from logs and diagnostics.

Restoring the encrypted bundle is not a substitute for application-data recovery. Databases such
as Plex and Immich can contain user IDs, password hashes, sessions, and application-owned identity
metadata. Their tested backups remain part of the rebuild contract.

GitHub Actions secrets are appropriate only for credentials that a CI workflow genuinely needs.
Production router, Proxmox, Cloudflare, application, and database credentials remain under the
SOPS/age recovery workflow and are decrypted on the trusted control plane.

The repository should be private because it contains the real topology, addresses, hostnames, and
recovery design. Private visibility does not relax any secret rule: authorized collaborators and
workflows can still read repository content, and an accidental plaintext secret remains a leak.

## Recipient and data-key rotation

To rotate the age identity without losing access:

1. Generate a new age identity and back it up.
2. Add its public recipient alongside the old recipient in `.sops.yaml`.
3. Run `sops updatekeys config/secrets/local.enc.yaml` while the old identity is still available.
4. Verify decryption using only the new identity.
5. Remove the old recipient from `.sops.yaml` and run `sops updatekeys` again.
6. Run `sops rotate --in-place config/secrets/local.enc.yaml` to renew the SOPS data key.
7. Run `task secrets:check` and then retire the old identity.

Token rotation is separate. Create the replacement token at the provider, update it through
`task secrets:edit`, validate it, and only then revoke the old token.

## Failure handling

`doctor` reports whether SOPS and age are installed, whether the encrypted file exists, and whether
it can be decrypted and validated. Decryption failures intentionally omit SOPS output so malformed
or unexpected provider responses cannot copy secret material into logs.

For SOPS and age behavior beyond this workflow, see the official
[SOPS documentation](https://github.com/getsops/sops) and
[age documentation](https://github.com/FiloSottile/age).
