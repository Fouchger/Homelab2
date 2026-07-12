"""Control-plane readiness checks."""

from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from homelabctl.configuration import ConfigurationError, load_config, resolve_config_path
from homelabctl.secrets import SecretError, load_secrets, resolve_secrets_path


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    detail: str
    required: bool = True

    @property
    def ok(self) -> bool:
        return self.status == "pass"


TOOLS: tuple[tuple[str, str, bool], ...] = (
    ("git", "Source control", True),
    ("task", "Task runner", True),
    ("uv", "Python environment", True),
    ("ssh", "Administrator bootstrap connection", True),
    ("tofu", "Infrastructure provisioning", False),
    ("ansible-playbook", "System configuration", False),
    ("sops", "Secret file encryption", True),
    ("age", "Secret key encryption", True),
)


def run_checks(
    config_path: str | Path | None = None, secrets_path: str | Path | None = None
) -> list[CheckResult]:
    path = resolve_config_path(config_path)
    config = None
    results = [
        CheckResult(
            "Python",
            "pass" if sys.version_info >= (3, 12) else "fail",
            platform.python_version(),
        ),
        CheckResult("Platform", "pass", f"{platform.system()} {platform.release()}"),
    ]

    try:
        config = load_config(path)
    except ConfigurationError as exc:
        results.append(CheckResult("Site configuration", "fail", str(exc)))
    else:
        results.append(
            CheckResult(
                "Site configuration",
                "pass",
                f"{config.site.name} ({config.site.environment}) · {path}",
            )
        )

    for executable, label, required in TOOLS:
        location = shutil.which(executable)
        results.append(
            CheckResult(
                label,
                "pass" if location else "warn" if not required else "fail",
                location or f"{executable} is not installed or not on PATH",
                required=required,
            )
        )

    encrypted_path = resolve_secrets_path(secrets_path)
    if not encrypted_path.is_file():
        results.append(
            CheckResult(
                "Encrypted credentials",
                "warn",
                f"Not initialized: {encrypted_path}",
                required=False,
            )
        )
    else:
        try:
            bundle = load_secrets(encrypted_path, config=config)
        except SecretError as exc:
            results.append(CheckResult("Encrypted credentials", "fail", str(exc), required=False))
        else:
            providers = ", ".join(bundle.provider_names())
            results.append(
                CheckResult(
                    "Encrypted credentials",
                    "pass",
                    f"Decrypted and validated for: {providers}",
                    required=False,
                )
            )
    return results


def checks_succeeded(results: list[CheckResult]) -> bool:
    return all(result.ok for result in results if result.required)
