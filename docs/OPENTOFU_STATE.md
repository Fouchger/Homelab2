# OpenTofu foundation and state

The control panel maps the validated site YAML into typed OpenTofu inputs. Secret values are never
written to a variable file: provider credentials are decrypted from SOPS in memory and supplied
only to the child process. Proxmox receives `TF_VAR_proxmox_api_token` and its provider environment;
Cloudflare receives `CLOUDFLARE_API_TOKEN` only when present. Both values are redacted from
diagnostics.

## Menu workflow

Open **Infrastructure** and run **Check OpenTofu foundation**. It performs these read-only steps:

1. checks OpenTofu formatting;
2. initializes the exact provider version from `.terraform.lock.hcl`;
3. validates the infrastructure project;
4. creates a non-destructive saved plan under the ignored `artifacts/` directory.

Generated non-secret site inputs are stored under ignored `.cache/tofu/`. Detailed, redacted
command output is appended to `logs/opentofu.log`. `task tofu:check` and `homelabctl tofu check`
provide the same operation for unattended troubleshooting.

For Phase 3 live acceptance, review the saved plan and apply that exact artifact through the
credential-aware wrapper:

```bash
task tofu:apply CONFIG=config/sites/local.yaml
```

The wrapper decrypts provider credentials in memory, supplies them only to the OpenTofu child
process, retains state locking, and refuses to calculate or apply a new plan. Do not invoke raw
`tofu apply` for a Cloudflare plan: the Cloudflare credential is intentionally not stored in the
plan file and would be absent from that process. If an apply partially succeeds, create and review
a new plan before retrying; never reuse the old plan.

## Provider reproducibility

The project constrains OpenTofu to the supported major version and pins `bpg/proxmox` and
`cloudflare/cloudflare` exactly. The committed dependency lock contains registry checksums for
supported platforms. Provider upgrades are deliberate: update the constraint, run
`tofu providers lock` for the required platforms, review release notes, and commit both changes
together.

The saved plan can contain public record content, resource identifiers, and infrastructure
metadata even though provider tokens are excluded. Treat it and state as sensitive operational
artifacts. Phase 3 remains plan-only in the control panel; the CLI wrapper exists for explicit
saved-plan acceptance, while the guarded interactive apply workflow is tracked by issue #9.

## State strategy

Local development uses OpenTofu's local backend. State and plans are ignored and must be treated as
sensitive. Local state is suitable only for one operator testing the foundation; it is not the
production collaboration mechanism.

Production uses an S3-compatible backend with server-side encryption, bucket versioning, and
native lock files. Provision the bucket independently, enable versioning, and restrict its
credentials to the state prefix. Then:

1. Copy `backend.production.tf.example` to the ignored `backend.production.tf`.
2. Copy `backend.production.hcl.example` to the ignored `backend.production.hcl` and replace its
   example values.
3. Supply backend credentials through environment variables or the platform identity—not in HCL.
4. Run `tofu init -reconfigure -backend-config=backend.production.hcl`.
5. Review the migration prompt carefully before moving any existing local state.

Never run two mutations without locking, use `-lock=false` for an apply, or force-unlock a lock
until the owning process is confirmed dead. Record any exceptional unlock in the operations log.

## Recovery

First stop all writers. Restore a previous version of the state object through the object-store
version history, then run a refresh-only plan to compare it with reality. Use `tofu state pull` for
an encrypted offline recovery copy. Avoid `tofu state push`; if it is unavoidable, back up the
remote state first and have a second operator verify the lineage and serial. A locally written
emergency state file after a backend failure must be secured immediately and pushed only after the
backend is healthy.
