#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

readonly REPOSITORY="${HOMELAB_REPOSITORY:-Fouchger/Homelab2}"
readonly BRANCH="${HOMELAB_BRANCH:-main}"
readonly INSTALL_DIR="${HOMELAB_INSTALL_DIR:-${HOME}/Homelab2}"
readonly BIN_DIR="${HOMELAB_BIN_DIR:-/usr/local/bin}"
readonly SOPS_VERSION="${HOMELAB_SOPS_VERSION:-3.13.2}"
readonly TOFU_VERSION="${HOMELAB_TOFU_VERSION:-1.12.1}"

APT_UPDATED=0

info() {
  printf '==> %s\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local exit_code="$?"
  printf 'ERROR: Installation failed near line %s (exit code %s).\n' "${BASH_LINENO[0]}" "$exit_code" >&2
  exit "$exit_code"
}
trap on_error ERR

is_debian_family() {
  [ -r /etc/os-release ] || return 1

  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-} ${ID_LIKE:-}" in
    *debian* | *ubuntu*) return 0 ;;
    *) return 1 ;;
  esac
}

run_as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    fail "Root access is required to install system packages. Install sudo or run this installer as root."
  fi
}

apt_update_once() {
  if [ "$APT_UPDATED" -eq 0 ]; then
    info "Refreshing the package index"
    run_as_root env DEBIAN_FRONTEND=noninteractive apt-get update
    APT_UPDATED=1
  fi
}

install_system_prerequisites() {
  local missing_packages=()

  command -v curl >/dev/null 2>&1 || missing_packages+=(curl)
  command -v git >/dev/null 2>&1 || missing_packages+=(git)
  command -v age >/dev/null 2>&1 || missing_packages+=(age)
  command -v ssh >/dev/null 2>&1 || missing_packages+=(openssh-client)
  command -v unzip >/dev/null 2>&1 || missing_packages+=(unzip)
  dpkg-query -W -f='${Status}' ca-certificates 2>/dev/null | grep -Fq 'install ok installed' || missing_packages+=(ca-certificates)

  if [ "${#missing_packages[@]}" -eq 0 ]; then
    info "System prerequisites are already installed"
    return
  fi

  apt_update_once
  info "Installing system prerequisites: ${missing_packages[*]}"
  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing_packages[@]}"
}

install_tofu() {
  local architecture
  local archive_name
  local temporary_directory

  if command -v tofu >/dev/null 2>&1; then
    info "OpenTofu is already installed"
    return
  fi

  case "$(uname -m)" in
    x86_64 | amd64) architecture="amd64" ;;
    aarch64 | arm64) architecture="arm64" ;;
    *) fail "OpenTofu installation does not support architecture: $(uname -m)" ;;
  esac

  archive_name="tofu_${TOFU_VERSION}_linux_${architecture}.zip"
  temporary_directory="$(mktemp -d)"
  info "Installing OpenTofu ${TOFU_VERSION}"
  curl -fsSLo "${temporary_directory}/${archive_name}" --proto '=https' --tlsv1.2 --retry 3 \
    "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/${archive_name}"
  curl -fsSLo "${temporary_directory}/SHA256SUMS" --proto '=https' --tlsv1.2 --retry 3 \
    "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/tofu_${TOFU_VERSION}_SHA256SUMS"
  (
    cd "$temporary_directory"
    grep -F " ${archive_name}" SHA256SUMS | sha256sum -c -
    unzip -q -- "$archive_name"
  )
  run_as_root install -m 0755 -- "${temporary_directory}/tofu" "${BIN_DIR}/tofu"
  rm -rf -- "$temporary_directory"
}

install_sops() {
  local architecture
  local binary_name
  local temporary_directory

  if command -v sops >/dev/null 2>&1; then
    info "SOPS is already installed"
    return
  fi

  case "$(uname -m)" in
    x86_64 | amd64) architecture="amd64" ;;
    aarch64 | arm64) architecture="arm64" ;;
    *) fail "SOPS installation does not support architecture: $(uname -m)" ;;
  esac

  binary_name="sops-v${SOPS_VERSION}.linux.${architecture}"
  temporary_directory="$(mktemp -d)"
  info "Installing SOPS ${SOPS_VERSION}"
  curl -fsSLo "${temporary_directory}/${binary_name}" --proto '=https' --tlsv1.2 --retry 3 \
    "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/${binary_name}"
  curl -fsSLo "${temporary_directory}/checksums.txt" --proto '=https' --tlsv1.2 --retry 3 \
    "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.checksums.txt"
  (
    cd "$temporary_directory"
    sha256sum -c checksums.txt --ignore-missing
  )
  run_as_root install -m 0755 -- "${temporary_directory}/${binary_name}" "${BIN_DIR}/sops"
  rm -rf -- "$temporary_directory"
}

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    info "uv is already installed"
    return
  fi

  info "Installing uv"
  curl -LsSf --proto '=https' --tlsv1.2 --retry 3 https://astral.sh/uv/install.sh |
    run_as_root env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh
}

install_task() {
  local installer

  if command -v task >/dev/null 2>&1; then
    info "Task is already installed"
    return
  fi

  info "Installing Task"
  installer="$(curl -fsSL --proto '=https' --tlsv1.2 --retry 3 https://taskfile.dev/install.sh)"
  run_as_root sh -c "$installer" -- -d -b "$BIN_DIR"
}

clone_or_update_repository() {
  local repository_url="https://github.com/${REPOSITORY}.git"
  local tracked_changes

  git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || fail "Invalid branch name: ${BRANCH}"

  if [ ! -e "$INSTALL_DIR" ]; then
    info "Cloning ${REPOSITORY} into ${INSTALL_DIR}"
    mkdir -p -- "$(dirname "$INSTALL_DIR")"
    git clone --branch "$BRANCH" --single-branch -- "$repository_url" "$INSTALL_DIR"
    return
  fi

  [ -d "$INSTALL_DIR/.git" ] || fail "${INSTALL_DIR} already exists and is not a Git repository."

  tracked_changes="$(git -C "$INSTALL_DIR" status --porcelain --untracked-files=no)"
  if [ -n "$tracked_changes" ]; then
    printf 'ERROR: %s contains tracked source changes:\n%s\n' "$INSTALL_DIR" "$tracked_changes" >&2
    fail "Commit or revert those source changes before updating. Runtime configuration, secrets, state, and logs are preserved automatically."
  fi

  info "Updating the existing repository in ${INSTALL_DIR}"
  git -C "$INSTALL_DIR" fetch "$repository_url" "$BRANCH"
  if git -C "$INSTALL_DIR" show-ref --verify --quiet "refs/heads/${BRANCH}"; then
    git -C "$INSTALL_DIR" checkout "$BRANCH"
  else
    git -C "$INSTALL_DIR" checkout -b "$BRANCH" FETCH_HEAD
  fi
  git -C "$INSTALL_DIR" merge --ff-only FETCH_HEAD
}

main() {
  printf '\nHomelab Control Plane installer\n\n'

  is_debian_family || fail "This installer supports Debian and Ubuntu (including WSL2)."
  install_system_prerequisites

  run_as_root mkdir -p "$BIN_DIR"
  export PATH="${BIN_DIR}:${PATH}"

  install_uv
  install_task
  install_sops
  install_tofu
  clone_or_update_repository

  printf '\nInstallation complete.\n\n'
  printf 'Next steps:\n'
  printf '  cd %q\n' "$INSTALL_DIR"
  printf '  task setup\n'
  printf '  task config:init\n'
  printf '  task menu\n\n'
}

main "$@"
