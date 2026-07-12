# Generic GitHub Repository Installer

A reusable Bash application for managing multiple public and private GitHub repository installations.

## Startup menu

At startup, the application lists all saved installations in this format:

```text
repository | branch | prod/dev | target directory
```

The user can:

- select an existing installation to clone or update
- choose `n` to add a new repository
- choose `q` to quit

## First installation of a repository

For each new installation, the application records:

- repository host and path
- public or private access result
- authentication method
- branch
- production or development mode
- target directory
- remote URL

The configuration is stored under:

```text
~/.config/repo-installer/installations/
```

A repository may be registered more than once. For example, the same repository can have separate production and development installations in different target directories.

## Public and private repositories

The application first tests anonymous HTTPS access.

- Public repositories use anonymous HTTPS.
- Private repositories use a working SSH key where available.
- If SSH is unavailable, an authenticated GitHub CLI session is checked.

The application does not store tokens, passwords or SSH private keys.

## Update policies

### Production

Production is synchronised exactly with the configured remote branch:

```bash
git fetch --prune origin <branch>
git checkout --force <branch>
git reset --hard origin/<branch>
git clean --force --directories
```

Local tracked changes and untracked files are removed. Store persistent data, secrets and generated files outside the repository.

### Development

Development protects local work:

- updates stop when uncommitted changes exist
- only fast-forward updates are allowed
- local work is never automatically committed, stashed or discarded

## Installation

```bash
chmod +x repo-installer.sh
./repo-installer.sh
```

To install it as a command:

```bash
sudo install -m 0755 repo-installer.sh /usr/local/bin/repo-installer
repo-installer
```

## Private repository authentication

### SSH

Configure an SSH key with access to the repository:

```bash
ssh -T git@github.com
```

A read-only deploy key is suitable for a production host that accesses one repository.

### GitHub CLI

```bash
gh auth login
gh auth setup-git
```

## Removing a saved installation

Delete its `.conf` file from:

```text
~/.config/repo-installer/installations/
```

This only removes the saved installer configuration. It does not delete the cloned repository.

## Compatibility

- Existing version 1 state files remain readable.
- New state files use version 2 naming, allowing multiple installations of the same repository.
- Automatic package installation supports Debian and Ubuntu.

## Interactive private-repository authentication

When anonymous HTTPS access fails, the installer now offers:

1. Sign in with GitHub CLI. The installer installs `gh` on Debian/Ubuntu when required, starts the browser/device login, and configures Git credential handling.
2. Retry SSH after an SSH key has been configured.
3. Retry automatic authentication detection.
4. Cancel without saving an incomplete installation.

For a headless server, GitHub CLI displays a one-time code and URL that can be completed from another device.

## Fine-grained personal access tokens

For a private repository, choose **Use a fine-grained personal access token** from the authentication menu.

Create the token in GitHub with:

- the correct resource owner
- access limited to the required repository
- **Contents: Read-only** for clone and pull operations
- an appropriate expiry date

The installer:

- reads the token without displaying it
- verifies repository access before saving it
- does not place the token in the repository URL or installation state file
- stores it in a separate user-private credential file under `~/.config/repo-installer/credentials/`
- applies file mode `0600`

The credential file is still plaintext on disk because it uses Git's built-in credential store. Restrict access to the Linux account and protect backups. GitHub CLI, Git Credential Manager, or an SSH deploy key provide stronger credential management where available.
