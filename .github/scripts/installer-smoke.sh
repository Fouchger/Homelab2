#!/usr/bin/env bash

set -Eeuo pipefail

readonly MOUNTED_SOURCE_DIR="/source"
readonly SOURCE_DIR="/tmp/installer-source"
readonly INSTALL_DIR="${HOMELAB_INSTALL_DIR:-/tmp/Homelab2}"
readonly TEST_BRANCH="${HOMELAB_BRANCH:-installer-smoke}"

cp -R "$MOUNTED_SOURCE_DIR" "$SOURCE_DIR"
bash "${SOURCE_DIR}/install.sh"

git --version
uv --version
task --version

test "$(git -C "$INSTALL_DIR" rev-parse HEAD)" = \
  "$(git --git-dir="${SOURCE_DIR}/.git" rev-parse "$TEST_BRANCH")"

cd "$INSTALL_DIR"
task setup
task config:init
uv run --locked --no-dev homelabctl validate --config config/sites/local.yaml
uv run --locked --no-dev homelabctl show --json \
  --config config/sites/local.yaml > /tmp/homelab-config.json
.venv/bin/python -m json.tool /tmp/homelab-config.json >/dev/null
.venv/bin/python -c 'import pydantic, textual, yaml'
.venv/bin/python -c \
  'import importlib.util; assert importlib.util.find_spec("pytest") is None; assert importlib.util.find_spec("ruff") is None'
