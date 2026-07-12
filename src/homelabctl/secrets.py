"""SOPS/age-backed runtime secret loading."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator

from homelabctl.configuration import find_project_root
from homelabctl.models import HomelabConfig, StrictModel

SECRETS_ENV_VAR = "HOMELAB_SECRETS"
DEFAULT_SECRETS_PATH = Path("config/secrets/local.enc.yaml")
DEFAULT_AGE_IDENTITY_PATH = Path("~/.config/sops/age/keys.txt")
AGE_RECIPIENT_PATTERN = re.compile(r"^age1[0-9a-z]{20,}$")
PLACEHOLDER_VALUES = {
    "replace-with-proxmox-api-token-secret",
    "replace-with-cloudflare-api-token",
}


class SecretError(RuntimeError):
    """Raised when encrypted runtime secrets are unavailable or invalid."""


class ProviderSecret(StrictModel):
    api_token: SecretStr = Field(description="Runtime API token; never serialize or log")

    @field_validator("api_token", mode="before")
    @classmethod
    def validate_api_token(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must contain a non-empty API token")
        normalized = value.strip()
        if normalized in PLACEHOLDER_VALUES:
            raise ValueError("still contains the generated placeholder; edit the encrypted file")
        return normalized


class SecretBundle(StrictModel):
    """Strict decrypted shape for provisioning credentials."""

    schema_version: Literal[1] = 1
    proxmox: ProviderSecret
    cloudflare: ProviderSecret | None = None

    def provider_environment(self) -> dict[str, str]:
        """Return the minimal environment expected by infrastructure providers."""

        environment = {
            "PROXMOX_VE_API_TOKEN": self.proxmox.api_token.get_secret_value(),
        }
        if self.cloudflare is not None:
            environment["CLOUDFLARE_API_TOKEN"] = self.cloudflare.api_token.get_secret_value()
        return environment

    def provider_names(self) -> tuple[str, ...]:
        names = ["Proxmox"]
        if self.cloudflare is not None:
            names.append("Cloudflare")
        return tuple(names)


def resolve_secrets_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    configured = os.environ.get(SECRETS_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    return (find_project_root() / DEFAULT_SECRETS_PATH).resolve()


def resolve_age_identity_path() -> Path:
    configured_path = os.environ.get("SOPS_AGE_KEY_FILE")
    return Path(configured_path or DEFAULT_AGE_IDENTITY_PATH).expanduser().resolve()


def _read_encrypted_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SecretError(f"Encrypted secret file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SecretError(f"Unable to inspect encrypted secret file: {path}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("sops"), dict):
        raise SecretError(
            f"Refusing to load plaintext or invalid secret file: {path}. "
            "A SOPS metadata block is required."
        )
    _require_encrypted_token(raw, "proxmox")
    if "cloudflare" in raw:
        _require_encrypted_token(raw, "cloudflare")
    return raw


def _require_encrypted_token(raw: dict[str, Any], provider: str) -> None:
    section = raw.get(provider)
    token = section.get("api_token") if isinstance(section, dict) else None
    if not isinstance(token, str) or not token.startswith("ENC["):
        raise SecretError(
            f"Refusing secret file with an unencrypted or missing {provider}.api_token value"
        )


def _find_sops(executable: str | None = None) -> str:
    resolved = executable or shutil.which("sops")
    if not resolved:
        raise SecretError("SOPS is not installed or is not on PATH")
    return resolved


def load_secrets(
    path: str | Path | None = None,
    *,
    config: HomelabConfig | None = None,
    sops_executable: str | None = None,
) -> SecretBundle:
    """Decrypt and validate a SOPS YAML document without writing plaintext to disk."""

    secret_path = resolve_secrets_path(path)
    _read_encrypted_mapping(secret_path)
    sops = _find_sops(sops_executable)
    try:
        completed = subprocess.run(
            [sops, "decrypt", "--output-type", "yaml", str(secret_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretError(
            "SOPS could not decrypt the secret file. Verify the age identity and try again."
        ) from exc
    if completed.returncode != 0:
        raise SecretError(
            "SOPS could not decrypt the secret file. Verify the age identity and try again."
        )
    try:
        decrypted = yaml.safe_load(completed.stdout)
    except yaml.YAMLError as exc:
        raise SecretError("SOPS returned invalid decrypted YAML") from exc
    if not isinstance(decrypted, dict):
        raise SecretError("Decrypted secret document must be a YAML mapping")
    try:
        bundle = SecretBundle.model_validate(decrypted)
    except ValidationError as exc:
        raise SecretError(_format_secret_validation_error(exc)) from exc
    if config is not None and config.cloudflare.domains and bundle.cloudflare is None:
        raise SecretError(
            "Decrypted secrets must include cloudflare.api_token when external domains are configured"
        )
    return bundle


def _format_secret_validation_error(error: ValidationError) -> str:
    lines = ["Decrypted secret validation failed:"]
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"])
        message = issue["msg"].removeprefix("Value error, ")
        lines.append(f"- {location}: {message}")
    return "\n".join(lines)


def secret_template() -> str:
    payload = {
        "schema_version": 1,
        "proxmox": {"api_token": "replace-with-proxmox-api-token-secret"},
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def initialize_secret_file(
    path: str | Path | None,
    *,
    age_recipient: str,
    force: bool = False,
    sops_executable: str | None = None,
) -> Path:
    """Create an encrypted placeholder document without persisting plaintext."""

    normalized_recipient = age_recipient.strip()
    if not AGE_RECIPIENT_PATTERN.fullmatch(normalized_recipient):
        raise SecretError("Enter a valid age recipient beginning with age1")
    secret_path = resolve_secrets_path(path)
    if secret_path.exists() and not force:
        raise SecretError(f"Encrypted secret file already exists: {secret_path}")
    sops = _find_sops(sops_executable)
    try:
        completed = subprocess.run(
            [
                sops,
                "encrypt",
                "--age",
                normalized_recipient,
                "--input-type",
                "yaml",
                "--output-type",
                "yaml",
                "/dev/stdin",
            ],
            input=secret_template(),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretError("SOPS could not create the encrypted secret file") from exc
    if completed.returncode != 0 or "sops:" not in completed.stdout:
        raise SecretError("SOPS could not create the encrypted secret file")
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(secret_path, completed.stdout)
    return secret_path


def write_sops_policy(age_recipient: str, *, start: Path | None = None) -> tuple[Path, bool]:
    """Create the repository recipient policy if one is not already present."""

    normalized_recipient = age_recipient.strip()
    if not AGE_RECIPIENT_PATTERN.fullmatch(normalized_recipient):
        raise SecretError("Enter a valid age recipient beginning with age1")
    policy_path = find_project_root(start) / ".sops.yaml"
    if policy_path.exists():
        return policy_path, False
    payload = yaml.safe_dump(
        {
            "creation_rules": [
                {
                    "path_regex": r"^config/secrets/.*\.enc\.yaml$",
                    "age": normalized_recipient,
                }
            ]
        },
        sort_keys=False,
    )
    _atomic_write(policy_path, payload)
    return policy_path, True


def ensure_age_identity(*, age_keygen_executable: str | None = None) -> tuple[Path, str, bool]:
    """Create the control-plane age identity when absent and return its public recipient."""

    identity_path = resolve_age_identity_path()
    age_keygen = age_keygen_executable or shutil.which("age-keygen")
    if not age_keygen:
        raise SecretError("age-keygen is not installed or is not on PATH")
    created = False
    if not identity_path.exists():
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            identity_path.parent.chmod(0o700)
        try:
            completed = subprocess.run(
                [age_keygen, "-o", str(identity_path)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretError("age-keygen could not create the control-plane identity") from exc
        if completed.returncode != 0 or not identity_path.is_file():
            raise SecretError("age-keygen could not create the control-plane identity")
        if os.name != "nt":
            identity_path.chmod(0o600)
        created = True
    try:
        completed = subprocess.run(
            [age_keygen, "-y", str(identity_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretError("age-keygen could not read the public recipient") from exc
    recipient = completed.stdout.strip()
    if completed.returncode != 0 or not AGE_RECIPIENT_PATTERN.fullmatch(recipient):
        raise SecretError("The configured age identity did not produce a valid public recipient")
    return identity_path, recipient, created


def ensure_secret_store(
    path: str | Path | None = None,
    *,
    age_keygen_executable: str | None = None,
    sops_executable: str | None = None,
) -> tuple[Path, Path, str, bool, bool]:
    """Ensure the age identity, SOPS policy, and encrypted placeholder file exist."""

    identity_path, recipient, identity_created = ensure_age_identity(
        age_keygen_executable=age_keygen_executable
    )
    secret_path = resolve_secrets_path(path)
    secret_created = False
    if not secret_path.exists():
        initialize_secret_file(
            secret_path, age_recipient=recipient, sops_executable=sops_executable
        )
        secret_created = True
    write_sops_policy(recipient, start=secret_path.parent)
    return secret_path, identity_path, recipient, secret_created, identity_created


def edit_secret_file(path: str | Path | None = None, *, sops_executable: str | None = None) -> Path:
    """Open an existing encrypted document using SOPS' protected editor workflow."""

    secret_path = resolve_secrets_path(path)
    _read_encrypted_mapping(secret_path)
    sops = _find_sops(sops_executable)
    try:
        completed = subprocess.run([sops, str(secret_path)], check=False)
    except OSError as exc:
        raise SecretError("SOPS could not open the encrypted secret file") from exc
    if completed.returncode != 0:
        raise SecretError("SOPS did not save the encrypted secret file")
    return secret_path


def set_proxmox_token(
    path: str | Path | None,
    api_token: str,
    *,
    sops_executable: str | None = None,
) -> Path:
    """Replace the encrypted Proxmox token using stdin so it never enters command arguments."""

    secret_path = resolve_secrets_path(path)
    _read_encrypted_mapping(secret_path)
    sops = _find_sops(sops_executable)
    try:
        completed = subprocess.run(
            [
                sops,
                "set",
                "--value-stdin",
                str(secret_path),
                '["proxmox"]["api_token"]',
            ],
            input=json.dumps(api_token),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SecretError("SOPS could not update the encrypted Proxmox token") from exc
    if completed.returncode != 0:
        raise SecretError("SOPS could not update the encrypted Proxmox token")
    return secret_path


def _atomic_write(path: Path, content: str) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        if os.name != "nt":
            path.chmod(0o640)
    except OSError as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise SecretError(f"Unable to write encrypted secret configuration: {path}") from exc
