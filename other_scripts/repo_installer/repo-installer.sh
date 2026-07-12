#!/usr/bin/env bash

# Generic GitHub Repository Installer
#
# Features:
#   - lists saved repository installations at startup
#   - allows an existing installation to be selected and updated
#   - allows new public or private repositories to be added
#   - remembers repository, branch, authentication, target and prod/dev mode
#   - applies safe, mode-specific update behaviour

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly APPLICATION_NAME="repo-installer"
readonly CURRENT_STATE_VERSION="3"
STATE_VERSION=""
readonly DEFAULT_GITHUB_HOST="github.com"
readonly CONFIG_ROOT="${XDG_CONFIG_HOME:-${HOME}/.config}/${APPLICATION_NAME}"
readonly STATE_DIRECTORY="${CONFIG_ROOT}/installations"
readonly CREDENTIAL_DIRECTORY="${CONFIG_ROOT}/credentials"

STATE_FILE=""
REPOSITORY=""
REPOSITORY_HOST="$DEFAULT_GITHUB_HOST"
REPOSITORY_PATH=""
BRANCH=""
INSTALLATION_MODE=""
TARGET_DIRECTORY=""
VISIBILITY=""
AUTHENTICATION_METHOD=""
REMOTE_URL=""
CREDENTIAL_FILE=""

log_info() { printf 'INFO: %s\n' "$*"; }
log_warning() { printf 'WARNING: %s\n' "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }
log_success() { printf 'SUCCESS: %s\n' "$*"; }

on_error() {
    local exit_code="$1"
    local line_number="$2"

    log_error "Operation failed at line ${line_number} with exit code ${exit_code}."
    exit "$exit_code"
}

trap 'on_error "$?" "$LINENO"' ERR

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

run_as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command_exists sudo; then
        sudo "$@"
    else
        log_error "Root privileges or sudo are required to install packages."
        exit 1
    fi
}

is_debian_family() {
    [ -r /etc/os-release ] || return 1

    # shellcheck disable=SC1091
    . /etc/os-release

    case "${ID:-} ${ID_LIKE:-}" in
        *debian*|*ubuntu*) return 0 ;;
        *) return 1 ;;
    esac
}

install_required_packages() {
    local packages=()

    command_exists git || packages+=("git")
    command_exists ssh || packages+=("openssh-client")
    command_exists curl || packages+=("curl")

    if [ "${#packages[@]}" -eq 0 ]; then
        return 0
    fi

    if ! is_debian_family; then
        log_error "Missing packages: ${packages[*]}"
        log_error "Automatic package installation currently supports Debian and Ubuntu."
        exit 1
    fi

    log_info "Installing required packages: ${packages[*]}"
    run_as_root apt-get update
    run_as_root env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y --no-install-recommends "${packages[@]}"
}

prompt_value() {
    local prompt_text="$1"
    local default_value="${2:-}"
    local entered_value

    if [ -n "$default_value" ]; then
        printf '%s [%s]: ' "$prompt_text" "$default_value" > /dev/tty
    else
        printf '%s: ' "$prompt_text" > /dev/tty
    fi

    IFS= read -r entered_value < /dev/tty
    printf '%s\n' "${entered_value:-$default_value}"
}

reset_configuration() {
    STATE_VERSION=""
    STATE_FILE=""
    REPOSITORY=""
    REPOSITORY_HOST="$DEFAULT_GITHUB_HOST"
    REPOSITORY_PATH=""
    BRANCH=""
    INSTALLATION_MODE=""
    TARGET_DIRECTORY=""
    VISIBILITY=""
    AUTHENTICATION_METHOD=""
    REMOTE_URL=""
    CREDENTIAL_FILE=""
}

normalise_repository() {
    local input="$1"

    input="${input#https://}"
    input="${input#http://}"
    input="${input#ssh://git@}"
    input="${input#git@}"
    input="${input%.git}"

    if [[ "$input" == *:* ]] && [[ "$input" != */*:* ]]; then
        REPOSITORY_HOST="${input%%:*}"
        REPOSITORY_PATH="${input#*:}"
    elif [[ "$input" == */*/* ]]; then
        REPOSITORY_HOST="${input%%/*}"
        REPOSITORY_PATH="${input#*/}"
    else
        REPOSITORY_HOST="$DEFAULT_GITHUB_HOST"
        REPOSITORY_PATH="$input"
    fi

    if [[ "$REPOSITORY_PATH" != */* ]]; then
        log_error "Repository must be in owner/name form or be a full Git URL."
        exit 1
    fi

    REPOSITORY="${REPOSITORY_HOST}/${REPOSITORY_PATH}"
}

safe_key() {
    printf '%s' "$1" |
        tr '[:upper:]' '[:lower:]' |
        tr '/:.' '---' |
        tr -cd 'a-z0-9_-'
}

set_new_state_file() {
    local repository_key
    local target_key

    mkdir -p "$STATE_DIRECTORY"
    chmod 700 "$CONFIG_ROOT" "$STATE_DIRECTORY" 2>/dev/null || true

    repository_key="$(safe_key "${REPOSITORY_HOST}/${REPOSITORY_PATH}")"
    target_key="$(safe_key "$TARGET_DIRECTORY")"
    STATE_FILE="${STATE_DIRECTORY}/${repository_key}--${INSTALLATION_MODE}--${target_key}.conf"
}

validate_mode() {
    case "$INSTALLATION_MODE" in
        prod|dev) ;;
        *)
            log_error "Installation mode must be prod or dev."
            exit 1
            ;;
    esac
}

validate_branch() {
    if ! git check-ref-format --branch "$BRANCH" >/dev/null 2>&1; then
        log_error "Invalid branch name: ${BRANCH}"
        exit 1
    fi
}

detect_visibility() {
    local anonymous_url="https://${REPOSITORY_HOST}/${REPOSITORY_PATH}.git"

    log_info "Checking whether the repository is publicly accessible."

    if GIT_TERMINAL_PROMPT=0 git ls-remote "$anonymous_url" HEAD >/dev/null 2>&1; then
        VISIBILITY="public"
    else
        VISIBILITY="private-or-inaccessible"
    fi
}


credential_file_for_repository() {
    local key

    key="$(printf '%s' "${REPOSITORY_HOST}/${REPOSITORY_PATH}" |
        tr '[:upper:]' '[:lower:]' |
        tr '/:.' '---' |
        tr -cd 'a-z0-9_-')"

    mkdir -p "$CREDENTIAL_DIRECTORY"
    chmod 700 "$CONFIG_ROOT" "$CREDENTIAL_DIRECTORY" 2>/dev/null || true
    printf '%s/%s.credentials\n' "$CREDENTIAL_DIRECTORY" "$key"
}

git_with_saved_credentials() {
    if [ "$AUTHENTICATION_METHOD" = "fine-grained-token" ]; then
        git \
            -c credential.useHttpPath=true \
            -c "credential.helper=store --file=${CREDENTIAL_FILE}" \
            "$@"
    else
        git "$@"
    fi
}

save_token_credential() {
    local username="$1"
    local token="$2"

    CREDENTIAL_FILE="$(credential_file_for_repository)"
    : > "$CREDENTIAL_FILE"
    chmod 600 "$CREDENTIAL_FILE"

    printf 'protocol=https\nhost=%s\npath=%s.git\nusername=%s\npassword=%s\n\n' \
        "$REPOSITORY_HOST" \
        "$REPOSITORY_PATH" \
        "$username" \
        "$token" |
        git credential-store --file="$CREDENTIAL_FILE" store

    chmod 600 "$CREDENTIAL_FILE"
}

authenticate_with_fine_grained_token() {
    local username
    local token
    local test_url="https://${REPOSITORY_HOST}/${REPOSITORY_PATH}.git"
    local temporary_credential_file

    username="$(prompt_value "GitHub username")"
    if [ -z "$username" ]; then
        log_warning "A GitHub username is required."
        return 1
    fi

    printf 'Fine-grained personal access token: ' > /dev/tty
    IFS= read -r -s token < /dev/tty
    printf '\n' > /dev/tty

    if [ -z "$token" ]; then
        log_warning "No token was entered."
        return 1
    fi

    temporary_credential_file="$(mktemp)"
    chmod 600 "$temporary_credential_file"
    trap 'rm -f "$temporary_credential_file"' RETURN

    printf 'protocol=https\nhost=%s\npath=%s.git\nusername=%s\npassword=%s\n\n' \
        "$REPOSITORY_HOST" \
        "$REPOSITORY_PATH" \
        "$username" \
        "$token" |
        git credential-store --file="$temporary_credential_file" store

    if ! GIT_TERMINAL_PROMPT=0 git \
        -c credential.useHttpPath=true \
        -c "credential.helper=store --file=${temporary_credential_file}" \
        ls-remote "$test_url" HEAD >/dev/null 2>&1; then
        log_warning "The token could not access this repository."
        trap - RETURN
        rm -f "$temporary_credential_file"
        token=""
        return 1
    fi

    save_token_credential "$username" "$token"
    token=""
    trap - RETURN
    rm -f "$temporary_credential_file"

    AUTHENTICATION_METHOD="fine-grained-token"
    REMOTE_URL="$test_url"
    VISIBILITY="private"
    return 0
}

github_cli_authenticated() {
    command_exists gh &&
        gh auth status --hostname "$REPOSITORY_HOST" >/dev/null 2>&1
}

ssh_access_available() {
    local ssh_url="git@${REPOSITORY_HOST}:${REPOSITORY_PATH}.git"

    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
        git ls-remote "$ssh_url" HEAD >/dev/null 2>&1
}

install_github_cli() {
    if command_exists gh; then
        return 0
    fi

    if ! is_debian_family; then
        log_error "GitHub CLI is not installed. Install gh and run the installer again."
        return 1
    fi

    log_info "Installing GitHub CLI."
    run_as_root apt-get update
    run_as_root env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y --no-install-recommends gh
}

authenticate_with_github_cli() {
    install_github_cli || return 1

    log_info "Starting GitHub CLI authentication for ${REPOSITORY_HOST}."
    gh auth login \
        --hostname "$REPOSITORY_HOST" \
        --git-protocol https \
        --web

    gh auth setup-git --hostname "$REPOSITORY_HOST"
    github_cli_authenticated
}

select_authentication_method() {
    local selection

    if [ "$VISIBILITY" = "public" ]; then
        AUTHENTICATION_METHOD="https-public"
        REMOTE_URL="https://${REPOSITORY_HOST}/${REPOSITORY_PATH}.git"
        return 0
    fi

    log_info "Anonymous HTTPS access failed; checking configured authentication."

    while :; do
        if ssh_access_available; then
            AUTHENTICATION_METHOD="ssh"
            REMOTE_URL="git@${REPOSITORY_HOST}:${REPOSITORY_PATH}.git"
            VISIBILITY="private"
            return 0
        fi

        if github_cli_authenticated; then
            gh auth setup-git --hostname "$REPOSITORY_HOST" >/dev/null 2>&1 || true
            AUTHENTICATION_METHOD="github-cli"
            REMOTE_URL="https://${REPOSITORY_HOST}/${REPOSITORY_PATH}.git"
            VISIBILITY="private"
            return 0
        fi

        printf '
The repository may be private, unavailable, or incorrectly named.
' > /dev/tty
        printf 'Choose an authentication action:
' > /dev/tty
        printf '  1) Sign in with GitHub CLI (recommended)
' > /dev/tty
        printf '  2) Use a fine-grained personal access token
' > /dev/tty
        printf '  3) Retry SSH after configuring an SSH key
' > /dev/tty
        printf '  4) Retry automatic detection
' > /dev/tty
        printf '  q) Cancel
' > /dev/tty
        printf 'Selection [1/2/3/4/q]: ' > /dev/tty
        IFS= read -r selection < /dev/tty

        case "$selection" in
            1)
                if authenticate_with_github_cli; then
                    AUTHENTICATION_METHOD="github-cli"
                    REMOTE_URL="https://${REPOSITORY_HOST}/${REPOSITORY_PATH}.git"
                    VISIBILITY="private"
                    return 0
                fi
                log_warning "GitHub CLI authentication was not completed."
                ;;
            2)
                if authenticate_with_fine_grained_token; then
                    return 0
                fi
                log_warning "Fine-grained token authentication was not completed."
                ;;
            3)
                printf '
Configure the SSH key in another terminal, then press Enter to retry.
' > /dev/tty
                IFS= read -r _ < /dev/tty
                ;;
            4)
                log_info "Retrying authentication detection."
                ;;
            q|Q)
                log_error "Repository setup cancelled."
                exit 1
                ;;
            *)
                log_warning "Enter 1, 2, 3, 4, or q."
                ;;
        esac
    done
}

discover_default_branch() {
    local detected_branch

    detected_branch="$(
        git_with_saved_credentials ls-remote --symref "$REMOTE_URL" HEAD 2>/dev/null |
            awk '/^ref:/ { sub("refs/heads/", "", $2); print $2; exit }'
    )"

    BRANCH="${detected_branch:-main}"
}

default_target_directory() {
    local repository_name="${REPOSITORY_PATH##*/}"

    case "$INSTALLATION_MODE" in
        prod) printf '%s/app/%s\n' "$HOME" "$repository_name" ;;
        dev) printf '%s/Github/%s\n' "$HOME" "$repository_name" ;;
    esac
}

write_state() {
    local temporary_file

    temporary_file="$(mktemp)"
    trap 'rm -f "$temporary_file"' RETURN

    {
        printf 'STATE_VERSION=%q\n' "$CURRENT_STATE_VERSION"
        printf 'REPOSITORY=%q\n' "$REPOSITORY"
        printf 'REPOSITORY_HOST=%q\n' "$REPOSITORY_HOST"
        printf 'REPOSITORY_PATH=%q\n' "$REPOSITORY_PATH"
        printf 'BRANCH=%q\n' "$BRANCH"
        printf 'INSTALLATION_MODE=%q\n' "$INSTALLATION_MODE"
        printf 'TARGET_DIRECTORY=%q\n' "$TARGET_DIRECTORY"
        printf 'VISIBILITY=%q\n' "$VISIBILITY"
        printf 'AUTHENTICATION_METHOD=%q\n' "$AUTHENTICATION_METHOD"
        printf 'REMOTE_URL=%q\n' "$REMOTE_URL"
        printf 'CREDENTIAL_FILE=%q\n' "$CREDENTIAL_FILE"
    } > "$temporary_file"

    install -m 0600 "$temporary_file" "$STATE_FILE"
    trap - RETURN
    rm -f "$temporary_file"
}

load_state_file() {
    local selected_file="$1"

    reset_configuration
    STATE_FILE="$selected_file"

    # State files are generated by this application and stored with mode 0600.
    # shellcheck disable=SC1090
    . "$STATE_FILE"

    case "${STATE_VERSION:-}" in
        1|2|3) ;;
        *)
            log_error "Unsupported state-file version in ${STATE_FILE}."
            exit 1
            ;;
    esac

    validate_mode
    validate_branch

    if [ "$AUTHENTICATION_METHOD" = "fine-grained-token" ]; then
        if [ -z "${CREDENTIAL_FILE:-}" ] || [ ! -f "$CREDENTIAL_FILE" ]; then
            log_error "The saved token credential file is missing for ${REPOSITORY}."
            log_error "Add the repository again or restore: ${CREDENTIAL_FILE:-unknown}"
            exit 1
        fi
    fi
}

read_state_summary() {
    local state_file="$1"

    (
        local REPOSITORY="unknown"
        local BRANCH="unknown"
        local INSTALLATION_MODE="unknown"
        local TARGET_DIRECTORY="unknown"

        # State files are generated by this application and stored with mode 0600.
        # shellcheck disable=SC1090
        . "$state_file"

        printf '%s | %s | %s | %s' \
            "$REPOSITORY" \
            "$BRANCH" \
            "$INSTALLATION_MODE" \
            "$TARGET_DIRECTORY"
    )
}

select_saved_or_new() {
    local state_files=()
    local selection
    local index

    mkdir -p "$STATE_DIRECTORY"

    while IFS= read -r -d '' STATE_FILE; do
        state_files+=("$STATE_FILE")
    done < <(find "$STATE_DIRECTORY" -maxdepth 1 -type f -name '*.conf' -print0 | sort -z)

    if [ "${#state_files[@]}" -eq 0 ]; then
        log_info "No saved repository installations were found."
        return 1
    fi

    printf '\nSaved repository installations:\n' > /dev/tty
    for index in "${!state_files[@]}"; do
        printf '  %d) %s\n' \
            "$((index + 1))" \
            "$(read_state_summary "${state_files[$index]}")" > /dev/tty
    done
    printf '  n) Add a new repository\n' > /dev/tty
    printf '  q) Quit\n' > /dev/tty

    while :; do
        printf 'Selection [1-%d/n/q]: ' "${#state_files[@]}" > /dev/tty
        IFS= read -r selection < /dev/tty

        case "$selection" in
            n|N)
                return 1
                ;;
            q|Q)
                exit 0
                ;;
            ''|*[!0-9]*)
                log_warning "Enter a repository number, n, or q."
                ;;
            *)
                if [ "$selection" -ge 1 ] && [ "$selection" -le "${#state_files[@]}" ]; then
                    load_state_file "${state_files[$((selection - 1))]}"
                    return 0
                fi
                log_warning "Selection is outside the available range."
                ;;
        esac
    done
}

add_new_repository() {
    local repository_input
    local suggested_target

    reset_configuration
    repository_input="$(prompt_value "GitHub repository (owner/name or URL)")"
    normalise_repository "$repository_input"

    detect_visibility
    select_authentication_method
    discover_default_branch
    BRANCH="$(prompt_value "Branch" "$BRANCH")"

    while :; do
        INSTALLATION_MODE="$(prompt_value "Installation mode (prod/dev)" "prod")"
        case "$INSTALLATION_MODE" in
            prod|dev) break ;;
            *) log_warning "Enter prod or dev." ;;
        esac
    done

    suggested_target="$(default_target_directory)"
    TARGET_DIRECTORY="$(prompt_value "Target directory" "$suggested_target")"

    validate_mode
    validate_branch
    set_new_state_file

    if [ -e "$STATE_FILE" ]; then
        log_error "This installation is already registered: ${STATE_FILE}"
        exit 1
    fi

    write_state
    log_success "Saved installation configuration to ${STATE_FILE}."
}

verify_remote_origin() {
    local actual_origin

    actual_origin="$(git -C "$TARGET_DIRECTORY" remote get-url origin)"

    if [ "$actual_origin" != "$REMOTE_URL" ]; then
        log_error "The target repository uses a different origin."
        log_error "Expected: ${REMOTE_URL}"
        log_error "Actual:   ${actual_origin}"
        exit 1
    fi
}

clone_repository() {
    mkdir -p "$(dirname "$TARGET_DIRECTORY")"

    if [ -e "$TARGET_DIRECTORY" ]; then
        log_error "Target already exists but is not a managed Git repository: ${TARGET_DIRECTORY}"
        exit 1
    fi

    log_info "Cloning ${REPOSITORY_PATH}, branch ${BRANCH}."
    git_with_saved_credentials clone --branch "$BRANCH" --single-branch "$REMOTE_URL" "$TARGET_DIRECTORY"

    if [ "$AUTHENTICATION_METHOD" = "fine-grained-token" ]; then
        git -C "$TARGET_DIRECTORY" config credential.useHttpPath true
        git -C "$TARGET_DIRECTORY" config credential.helper "store --file=${CREDENTIAL_FILE}"
    fi
}

update_production_repository() {
    log_info "Synchronising production checkout with origin/${BRANCH}."

    git_with_saved_credentials -C "$TARGET_DIRECTORY" fetch --prune origin "$BRANCH"
    git -C "$TARGET_DIRECTORY" checkout --force "$BRANCH"
    git -C "$TARGET_DIRECTORY" reset --hard "origin/${BRANCH}"
    git -C "$TARGET_DIRECTORY" clean -fd
}

update_development_repository() {
    if [ -n "$(git -C "$TARGET_DIRECTORY" status --porcelain)" ]; then
        log_error "Development checkout contains local changes."
        log_error "Commit or stash them before updating."
        exit 1
    fi

    log_info "Fast-forwarding development checkout from origin/${BRANCH}."

    git_with_saved_credentials -C "$TARGET_DIRECTORY" fetch --prune origin "$BRANCH"
    git -C "$TARGET_DIRECTORY" checkout "$BRANCH"
    git -C "$TARGET_DIRECTORY" merge --ff-only "origin/${BRANCH}"
}

clone_or_update_repository() {
    if [ ! -e "$TARGET_DIRECTORY" ]; then
        clone_repository
        return 0
    fi

    if [ ! -d "${TARGET_DIRECTORY}/.git" ]; then
        log_error "Target exists but is not a Git repository: ${TARGET_DIRECTORY}"
        exit 1
    fi

    verify_remote_origin

    case "$INSTALLATION_MODE" in
        prod) update_production_repository ;;
        dev) update_development_repository ;;
    esac
}

show_configuration() {
    printf '\n'
    printf 'Repository:       %s\n' "$REPOSITORY"
    printf 'Visibility:       %s\n' "$VISIBILITY"
    printf 'Authentication:   %s\n' "$AUTHENTICATION_METHOD"
    printf 'Branch:           %s\n' "$BRANCH"
    printf 'Installation:     %s\n' "$INSTALLATION_MODE"
    printf 'Target directory: %s\n' "$TARGET_DIRECTORY"
    printf 'State file:       %s\n' "$STATE_FILE"
    printf '\n'
}

main() {
    printf '%s\n' '=========================================================='
    printf '%s\n' '          Generic GitHub Repository Installer'
    printf '%s\n' '=========================================================='

    install_required_packages

    if ! select_saved_or_new; then
        add_new_repository
    fi

    show_configuration
    clone_or_update_repository
    log_success "Repository is ready at ${TARGET_DIRECTORY}."
}

main "$@"
