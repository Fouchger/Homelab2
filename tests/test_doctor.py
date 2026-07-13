from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from homelabctl.configuration import save_config
from homelabctl.doctor import checks_succeeded, run_checks
from homelabctl.models import default_config
from homelabctl.secrets import SecretError


def test_invalid_configured_provider_credentials_fail_readiness(
    tmp_path: Path, monkeypatch
) -> None:
    config = default_config()
    config.cloudflare.domains = ["example.com"]
    config_path = save_config(config, tmp_path / "site.yaml")
    secrets_path = tmp_path / "secrets.enc.yaml"
    secrets_path.write_text("encrypted-test-placeholder", encoding="utf-8")
    monkeypatch.setattr("homelabctl.doctor.shutil.which", lambda executable: f"/bin/{executable}")
    monkeypatch.setattr(
        "homelabctl.doctor.load_secrets",
        Mock(side_effect=SecretError("cloudflare.api_token is required")),
    )

    results = run_checks(config_path, secrets_path)

    credentials = next(result for result in results if result.name == "Encrypted credentials")
    assert credentials.status == "fail"
    assert credentials.required
    assert not checks_succeeded(results)
