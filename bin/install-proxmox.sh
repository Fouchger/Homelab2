#!/usr/bin/env bash
#
# install-proxmox.sh — creates or updates Controlplane on a Proxmox VE
# host, from a single command.
#
# Usage (run as root, in the Proxmox VE host shell):
#   curl -fsSL https://raw.githubusercontent.com/<PUBLIC_REPOSITORY>/main/bin/install-proxmox.sh \
#     | bash -s -- --release vX.Y.Z
#
# This script does exactly one job: fetch the pinned release, verify it
# against its published SHA-256 checksum, extract it, and hand off to
# that release's own provisioning/proxmox/install.sh. It never installs
# or configures anything itself, and it never decides whether this is a
# fresh install or an update — everything host-specific, including
# whether a tagged Controlplane LXC already exists, lives in the release
# it fetches (provisioning/proxmox/install.sh queries the Proxmox host
# for that itself), so this bootstrap stays stable across releases.
#
# Re-running this exact command later, with a newer --release, is how
# you update an existing install: provisioning/proxmox/install.sh finds
# the existing tagged LXC and upgrades it in place (new code, same
# database/secrets) rather than creating a second one. Pass --recreate
# to destroy the existing LXC and build a fresh one instead — see that
# script's own header for exactly what each mode does.
#
# Touching an existing LXC (update-in-place or --recreate) always asks
# for confirmation first, read directly from the terminal. Pass --yes to
# skip that prompt for scripted/CI runs.
#
# See docs/standards/git-workflow.md for how a release gets published,
# and docs/design/tool-stack.md for why the release is fetched from the
# public mirror rather than this (private) repo.

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The public repo releases are published to. This script itself only ever
# runs by being curl'd from that same repo, so it's a plain constant here,
# not read from anywhere — keep it in sync with the PUBLIC_REPOSITORY
# repository variable in Homelab-Private's Settings, by hand, if it ever
# changes.
readonly REPO="Fouchger/Homelab"

readonly INSTALL_ROOT="/opt/controlplane"
# Informational breadcrumb only, written on the PROXMOX HOST itself at
# the end of a run -- NOT a gate (provisioning/proxmox/install.sh is what
# actually decides create vs. update vs. recreate, by querying the host
# for a tagged LXC, not by checking a file here).
readonly MARKER_FILE="${INSTALL_ROOT}/LAST_BOOTSTRAP_RELEASE"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

RELEASE=""
RECREATE=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: $(basename "$0") --release vX.Y.Z [--recreate]

  --release vX.Y.Z   Required. The exact tag to install (e.g. v2.5.0, or
                     a pre-release tag like v2.6.0-rc.1 for the Test
                     channel). Never omit this and never point it at a
                     moving target — every install is pinned.
  --recreate         Destroy the existing tagged Controlplane LXC (if
                     any) and create a fresh one, instead of the default
                     behavior of upgrading an existing one in place.
                     Irreversible -- everything on that container is
                     gone, including its database, unless you've backed
                     it up yourself. Without this flag, re-running with
                     a newer --release updates the existing install
                     (new code, same database/secrets); with no
                     existing install, it's a normal fresh create
                     either way.
  -y, --yes          Skip the confirmation prompt before updating or
                     recreating an existing LXC. For scripted/CI runs;
                     interactively, always confirm first instead of
                     passing this by habit.
  -h, --help         Show this help text.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --release)
      RELEASE="${2:-}"
      shift 2
      ;;
    --release=*)
      RELEASE="${1#*=}"
      shift
      ;;
    --recreate)
      RECREATE=1
      shift
      ;;
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unrecognized argument '$1'"
      ;;
  esac
done

if [ -z "$RELEASE" ]; then
  usage >&2
  fail "--release is required -- see above."
fi

if ! [[ "$RELEASE" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-test\.[0-9]+)?$ ]]; then
  fail "'${RELEASE}' doesn't look like a release tag (expected vMAJOR.MINOR.PATCH, optionally -test.N for the Test channel)."
fi

VERSION="${RELEASE#v}"

# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
  fail "this script must run as root (it provisions an LXC container and manages /opt/controlplane)."
fi

if ! command -v pveversion >/dev/null 2>&1; then
  fail "'pveversion' not found -- this doesn't look like a Proxmox VE host."
fi

for cmd in curl tar sha256sum; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    fail "required command '${cmd}' not found on this host."
  fi
done

# ---------------------------------------------------------------------------
# Fetch, verify, extract
# ---------------------------------------------------------------------------

WORKDIR="$(mktemp -d /tmp/controlplane-install.XXXXXX)"
cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

ARCHIVE="controlplane-${VERSION}.tar.gz"
BASE_URL="https://github.com/${REPO}/releases/download/${RELEASE}"

log "Fetching ${RELEASE} from ${REPO}"

if ! curl -fsSL --retry 3 --retry-delay 2 -o "${WORKDIR}/${ARCHIVE}" "${BASE_URL}/${ARCHIVE}"; then
  fail "failed to download ${ARCHIVE} -- check the release tag exists at https://github.com/${REPO}/releases/tag/${RELEASE}"
fi

if ! curl -fsSL --retry 3 --retry-delay 2 -o "${WORKDIR}/${ARCHIVE}.sha256" "${BASE_URL}/${ARCHIVE}.sha256"; then
  fail "failed to download the checksum file for ${RELEASE} -- refusing to install an unverifiable archive."
fi

log "Verifying checksum"
if ! (cd "$WORKDIR" && sha256sum -c "${ARCHIVE}.sha256"); then
  fail "checksum verification FAILED for ${ARCHIVE}. The download is corrupt or has been tampered with -- refusing to extract or execute it."
fi

log "Extracting"
tar -xzf "${WORKDIR}/${ARCHIVE}" -C "$WORKDIR"

EXTRACTED_DIR="${WORKDIR}/controlplane-${VERSION}"
NEXT_STAGE="${EXTRACTED_DIR}/provisioning/proxmox/install.sh"

if [ ! -f "$NEXT_STAGE" ]; then
  fail "${RELEASE} doesn't contain provisioning/proxmox/install.sh -- this release can't be installed on Proxmox. If you're seeing this on an official release, please report it."
fi

# ---------------------------------------------------------------------------
# Hand off to the release's own installer
# ---------------------------------------------------------------------------

log "Handing off to provisioning/proxmox/install.sh"
chmod +x "$NEXT_STAGE"
CONTROLPLANE_RELEASE="$RELEASE" \
CONTROLPLANE_VERSION="$VERSION" \
CONTROLPLANE_SOURCE_DIR="$EXTRACTED_DIR" \
CONTROLPLANE_INSTALL_ROOT="$INSTALL_ROOT" \
CONTROLPLANE_RECREATE="$RECREATE" \
CONTROLPLANE_ASSUME_YES="$ASSUME_YES" \
  "$NEXT_STAGE"

# Informational only (see MARKER_FILE's own comment above) -- written
# after a successful run, not used to gate anything on the next one.
mkdir -p "$INSTALL_ROOT"
echo "$RELEASE" > "$MARKER_FILE"
ok "Controlplane ${RELEASE} installation completed."
