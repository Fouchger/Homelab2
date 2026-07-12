"""Configuration discovery, validation, and atomic persistence."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from homelabctl.models import HomelabConfig, default_config

CONFIG_ENV_VAR = "HOMELAB_CONFIG"


class ConfigurationError(RuntimeError):
    """Raised when a configuration cannot be loaded or validated."""


def find_project_root(start: Path | None = None) -> Path:
    """Find the nearest repository root without relying on Git being installed."""

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() or (candidate / ".git").exists():
            return candidate
    return current


def default_config_path(start: Path | None = None) -> Path:
    configured = os.environ.get(CONFIG_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    return find_project_root(start) / "config" / "sites" / "local.yaml"


def resolve_config_path(path: str | Path | None) -> Path:
    return Path(path).expanduser().resolve() if path else default_config_path()


def load_config(path: str | Path | None = None) -> HomelabConfig:
    config_path = resolve_config_path(path)
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Unable to read {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError(f"Configuration root must be a YAML mapping: {config_path}")
    try:
        return HomelabConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(format_validation_error(exc)) from exc


def save_config(config: HomelabConfig, path: str | Path | None = None) -> Path:
    """Atomically replace a config file so interruption cannot leave partial YAML."""

    config_path = resolve_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(
        config.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            dir=config_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, config_path)
        if os.name != "nt":
            config_path.chmod(0o640)
    except OSError as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise ConfigurationError(f"Unable to save {config_path}: {exc}") from exc
    return config_path


def initialize_config(path: str | Path | None = None, *, force: bool = False) -> Path:
    config_path = resolve_config_path(path)
    if config_path.exists() and not force:
        raise ConfigurationError(f"Configuration already exists: {config_path}")
    return save_config(default_config(), config_path)


def write_schema(path: str | Path) -> Path:
    import json

    schema_path = Path(path).expanduser().resolve()
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(HomelabConfig.model_json_schema(), indent=2) + "\n"
    temporary = schema_path.with_suffix(f"{schema_path.suffix}.tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, schema_path)
    return schema_path


def format_validation_error(error: ValidationError) -> str:
    lines = ["Configuration validation failed:"]
    for issue in error.errors(include_url=False):
        location = ".".join(str(part) for part in issue["loc"])
        message = issue["msg"].removeprefix("Value error, ")
        lines.append(f"- {location}: {message}")
    return "\n".join(lines)


def redacted_mapping(config: HomelabConfig) -> dict[str, Any]:
    """Return display-safe settings. Secret values are intentionally not in the model."""

    return config.model_dump(mode="json")
