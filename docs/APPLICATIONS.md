# Curated applications

Curated applications are installed inside existing OpenTofu-owned guests. OpenTofu remains the
only guest lifecycle owner; application operations never create, replace, destroy, resize, or
publish DNS for a guest.

## Uptime Kuma pilot

The initial allowlist contains Uptime Kuma `2.4.0`. Configure one application against an existing
container key:

```yaml
applications:
  uptime-kuma:
    type: uptime-kuma
    guest: monitoring
    enabled: true
    port: 3001
```

Run `task ansible:apply` first so the dedicated automation account exists. Then use:

```text
task applications:plan   Display the exact reviewed revision and artifact checksums
task applications:check  Run the adapter in check mode
task applications:apply  Apply after review and require a successful HTTP health check
```

The control panel exposes the same preview and confirmed apply operations under Infrastructure.
Application connections use the dedicated automation account with explicit privilege escalation.

## Supply-chain boundary

The Phase 4 curated application adapter never executes Community Scripts' host-side creator, never
runs `curl | bash`, and
never retrieves executable code from a moving branch. The Community Scripts revision, license,
reviewed installer blob, Uptime Kuma release, and verified SHA-256 hashes are recorded in
[`../ansible/applications/UPSTREAM.md`](../ansible/applications/UPSTREAM.md).

Phase 6 introduces a distinct, guarded creator adapter for new replacement guests. It does not
weaken this in-guest application boundary: the creator is commit-pinned and checksum-verified,
targets only an unused identity, and must complete the OpenTofu import and zero-change adoption
contract in [`PHASE_6_EXECUTION_PLAN.md`](PHASE_6_EXECUTION_PLAN.md).

Uptime Kuma's source and prebuilt frontend are downloaded from immutable release URLs and verified
before extraction. Production npm dependencies are resolved from the release lockfile, whose
entries carry registry integrity hashes.

## Data, update, and rollback

Persistent application data lives at `/var/lib/uptime-kuma`. Versioned application code lives
under `/opt/uptime-kuma/releases/<version>`, and `/opt/uptime-kuma/current` selects the approved
release. Re-running the same adapter does not reinstall dependencies or create another guest.

An update requires a code review that changes the pinned version and both artifact hashes, followed
by disposable check, apply, health, second-apply idempotence, and rebuild acceptance. The existing
release and persistent data are retained. Roll back by restoring the previous reviewed manifest
and playbook values and applying again; the controlled symlink switches back before the service
health check.

If installation fails, inspect `logs/applications.log`. The current release and data are not
removed. Correct the failed prerequisite or artifact review, run check again, then apply. If a
guest must be rebuilt, OpenTofu recreates it, the baseline restores the automation boundary, and
the application adapter reinstalls the same approved snapshot. Data restoration is a separate
backup operation and is never silently performed by this adapter.
