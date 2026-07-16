# Cloudflare DNS provisioning

## Outcome

Phase 3 turns each entry in `cloudflare.records` into one public DNS record in an existing active
Cloudflare zone. Supported types are `A`, `AAAA`, and `CNAME`. Records default to DNS-only
(`proxied: false`) and Cloudflare automatic TTL (`ttl: 1`).

The provider looks up each used zone by exact name and refuses to continue unless exactly one
active zone is returned. OpenTofu does not create zones.

## Credential and permissions

Store the Cloudflare API token only in the SOPS/age secret file. The token should be scoped to the
specific zones and needs zone-read plus DNS-read/write permissions. A Cloudflare token is required
only when at least one record is declared; listing domains alone remains a valid offline
configuration.

Use the masked control-panel workflow or the CLI to set and check the token:

```bash
task secrets:edit
task secrets:check
```

## Configuration

Declare existing zones and explicit records in the ignored site file:

```yaml
cloudflare:
  domains:
    - example.com
    - example.net
  records:
    - zone: example.com
      name: app
      type: A
      content: REPLACE_WITH_A_PUBLIC_IPV4_ADDRESS
      ttl: 1
      proxied: false
    - zone: example.net
      name: www
      type: CNAME
      content: app.example.com
      ttl: 300
      proxied: true
```

`name` is relative to `zone`; use `@` for the zone apex. The first placeholder is intentionally
not valid—replace it with the real public address before validation.

The configuration layer rejects:

- records whose zone is absent from `cloudflare.domains`;
- duplicate zone/type/name identities;
- private, loopback, reserved, or wrong-version A/AAAA targets;
- malformed CNAME targets and unsupported record types;
- TTL values other than automatic or 60–86400 seconds;
- any public name or CNAME target at or below the internal `site.domain`.

## Ownership rule

Every record has exactly one owner:

- records in `cloudflare.records` are owned exclusively by OpenTofu;
- a future DDNS service may own a separate edge record that is absent from OpenTofu;
- OpenTofu-managed CNAMEs may point at that DDNS record;
- tunnel installers and application scripts may not create or mutate OpenTofu-owned records.

This avoids the perpetual drift and accidental deletion caused when two tools manage the same
record.

## Plan and acceptance

Validate the site file, confirm the Cloudflare credential, and create the saved plan:

```bash
task config:validate
task secrets:check
task tofu:check
```

Review every zone, fully qualified name, type, content, TTL, proxy flag, addition, and deletion.
Phase 3 is plan-only in the control panel. Disposable acceptance should prove create, update, and
destroy in every configured zone from an explicitly reviewed saved plan before issue #7 is closed.
Apply only that saved plan through `task tofu:apply`; this wrapper supplies the in-memory
Cloudflare credential that a raw `tofu apply` process does not receive.
