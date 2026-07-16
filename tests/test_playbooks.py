from __future__ import annotations

from pathlib import Path

import yaml


def test_baseline_package_access_is_bounded() -> None:
    playbook = yaml.safe_load(
        (Path(__file__).parents[1] / "ansible" / "baseline.yml").read_text(encoding="utf-8")
    )
    tasks = playbook[0]["tasks"]
    timeout_policy = next(task for task in tasks if task["name"] == "Set safe Debian package time limits")
    assert 'Acquire::http::Timeout "30";' in timeout_policy["ansible.builtin.copy"]["content"]
    assert 'DPkg::Lock::Timeout "60";' in timeout_policy["ansible.builtin.copy"]["content"]
    cache_refresh = next(
        task for task in tasks if task["name"] == "Refresh package cache (up to 90 seconds)"
    )
    assert cache_refresh["ansible.builtin.command"]["argv"][:3] == [
        "timeout",
        "--foreground",
        "90s",
    ]


def test_uptime_kuma_preview_skips_tasks_that_need_real_guest_files() -> None:
    playbook = yaml.safe_load(
        (Path(__file__).parents[1] / "ansible" / "applications" / "uptime-kuma.yml").read_text(
            encoding="utf-8"
        )
    )
    tasks = playbook[0]["tasks"]
    prerequisites = next(task for task in tasks if task["name"] == "Install pinned-adapter prerequisites")
    assert "chromium" not in prerequisites["ansible.builtin.apt"]["name"]
    extraction = next(task for task in tasks if task["name"] == "Extract the approved application source")
    assert extraction["when"] == "not ansible_check_mode"
