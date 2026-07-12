#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

readonly REPOSITORY="${HOMELAB_REPOSITORY:-Fouchger/Homelab2}"
readonly BRANCH="${HOMELAB_BRANCH:-main}"
readonly INSTALL_DIR="${HOMELAB_INSTALL_DIR:-${HOME}/Homelab2}"
readonly BIN_DIR="${HOMELAB_BIN_DIR:-/usr/local/bin}"

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
  dpkg-query -W -f='${Status}' ca-certificates 2>/dev/null | grep -Fq 'install ok installed' || missing_packages+=(ca-certificates)

  if [ "${#missing_packages[@]}" -eq 0 ]; then
    info "System prerequisites are already installed"
    return
  fi

  apt_update_once
  info "Installing system prerequisites: ${missing_packages[*]}"
  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing_packages[@]}"
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

  git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || fail "Invalid branch name: ${BRANCH}"

  if [ ! -e "$INSTALL_DIR" ]; then
    info "Cloning ${REPOSITORY} into ${INSTALL_DIR}"
    mkdir -p -- "$(dirname "$INSTALL_DIR")"
    git clone --branch "$BRANCH" --single-branch -- "$repository_url" "$INSTALL_DIR"
    return
  fi

  [ -d "$INSTALL_DIR/.git" ] || fail "${INSTALL_DIR} already exists and is not a Git repository."

  if [ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]; then
    fail "${INSTALL_DIR} contains local changes. Commit or stash them before running the installer again."
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
  clone_or_update_repository

  printf '\nInstallation complete.\n\n'
  printf 'Next steps:\n'
  printf '  cd %q\n' "$INSTALL_DIR"
  printf '  task setup\n'
  printf '  task config:init\n'
  printf '  task menu\n\n'
}

main "$@"
