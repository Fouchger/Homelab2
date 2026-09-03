# Controlplane Platform

Controlplane provisions and manages a homelab's infrastructure — DNS,
metrics, logs, dashboards, a Cloudflare tunnel — from one web app,
instead of hand-configuring each service on its own LXC. It runs
production on Proxmox VE, and a closely matched environment in WSL 2
mirrors the same install for development and testing.

Every install is pinned to a specific published release and verified
against its SHA-256 checksum before anything runs — there's no
"install latest" path that could silently pull something unverified.

## Install

Replace `vX.Y.Z` with the release you want — the current Stable and
Test versions are listed on the
[Releases page](https://github.com/Fouchger/Homelab/releases) and in
this repo's own [`releases/index.json`](releases/index.json) on the
`main` branch (Stable) or the
[`test`](https://github.com/Fouchger/Homelab/blob/test/releases/index.json)
branch (Test). Don't substitute `latest` for a real tag — every install
is pinned on purpose.

> No release has been published yet. The commands below are correct
> once a release is cut from the Actions tab and `release.yml` publishes
> it — see
> [`docs/standards/git-workflow.md`](docs/standards/git-workflow.md#versioning--semantic-versioning-with-a-computed-prerelease-number)
> for how a version gets cut.

**Proxmox VE** — run as `root` in the Proxmox host shell:

```bash
curl -fsSL https://raw.githubusercontent.com/Fouchger/Homelab/main/bin/install-proxmox.sh \
  | bash -s -- --release vX.Y.Z
```

**Windows WSL 2** — run in Windows PowerShell. Elevation is only
requested if WSL itself still needs enabling, and only for that one
step:

```powershell
& ([scriptblock]::Create((Invoke-RestMethod `
    'https://raw.githubusercontent.com/Fouchger/Homelab/main/bin/install-wsl.ps1'))) `
    -Release 'vX.Y.Z'
```

Both scripts do exactly one job: fetch the pinned release, verify its
checksum, extract it, and hand off to that release's own
`provisioning/proxmox/install.sh` or `provisioning/wsl/install.sh`.
Nothing platform-specific lives in the bootstrap script itself, so it
stays stable across releases.

## Release channels

| Channel | Tag pattern | Intended for |
| --- | --- | --- |
| Stable | `vMAJOR.MINOR.PATCH` | Production installs |
| Test | `vMAJOR.MINOR.PATCH-test.N` | Trying a change before it reaches Stable |

A Test release is a fresh cut of the `test` branch. A Stable release is
never cut directly from a branch snapshot — it's a *promotion* of a Test
release that has already been validated against real hardware or WSL and
has a recorded 'passed' result, cut from `main` once that validation
holds (see
[`docs/standards/git-workflow.md`](docs/standards/git-workflow.md#promotion--test-to-stable)).

Switching an existing install's channel, installing a different
version, and rolling back are all done from the running app's Releases
page — never by re-running the bootstrap script over an existing
install.

## Verification

Every release ships as a source archive plus a `.sha256` checksum file,
both attached to its GitHub Release. The bootstrap scripts download
both and refuse to extract or execute the archive if the checksum
doesn't match. The same archive and checksum are what the running app
itself downloads for an in-place version change or rollback.

## Development

This repository is a public mirror, published on demand from the
private development repository — see
[`docs/standards/git-workflow.md`](docs/standards/git-workflow.md) for
the branching model, and [`docs/design/`](docs/design/) for the
platform's functional design, tool choices, and module boundaries.
Want to report a bug, suggest something, or contribute code? See
[`CONTRIBUTING.md`](CONTRIBUTING.md). Found a security issue? See
[`SECURITY.md`](SECURITY.md) instead of opening a public issue.

## License

[MIT](LICENSE) — see [`CHANGELOG.md`](CHANGELOG.md) for what's changed
release to release.
