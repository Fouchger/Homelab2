from __future__ import annotations

from pathlib import Path

import yaml


def test_baseline_package_access_is_bounded() -> None:
    playbook = yaml.safe_load(
        (Path(__file__).parents[1] / "ansible" / "baseline.yml").read_text(encoding="utf-8")
    )
    tasks = playbook[0]["tasks"]
    timeout_policy = next(
        task for task in tasks if task["name"] == "Set safe Debian package time limits"
    )
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
    prerequisites = next(
        task for task in tasks if task["name"] == "Install pinned-adapter prerequisites"
    )
    assert "chromium" not in prerequisites["ansible.builtin.apt"]["name"]
    extraction = next(
        task for task in tasks if task["name"] == "Extract the approved application source"
    )
    assert extraction["when"] == "not ansible_check_mode"


def test_uptime_kuma_dependencies_run_as_service_account_without_ansible_acl_switch() -> None:
    playbook = yaml.safe_load(
        (Path(__file__).parents[1] / "ansible" / "applications" / "uptime-kuma.yml").read_text(
            encoding="utf-8"
        )
    )
    task = next(
        task
        for task in playbook[0]["tasks"]
        if task["name"] == "Install locked production dependencies"
    )
    assert "become_user" not in task
    assert task["ansible.builtin.command"]["argv"][:4] == [
        "/usr/sbin/runuser",
        "-u",
        "uptime-kuma",
        "--",
    ]


def test_technitium_adapter_is_pinned_non_root_and_hides_credentials() -> None:
    path = Path(__file__).parents[1] / "ansible" / "applications" / "technitium.yml"
    raw = path.read_text(encoding="utf-8")
    playbook = yaml.safe_load(raw)
    tasks = playbook[0]["tasks"]

    assert "15.4.0" in raw
    assert "461ac09d4304ace85093fc17b10a7ee13a8796eae0adb4393866bd4d66ab283f" in raw
    assert "10.0.10" in raw
    service = next(
        task for task in tasks if task["name"] == "Install the hardened Technitium service"
    )
    unit = service["ansible.builtin.copy"]["content"]
    assert "User=dns-server" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=CAP_NET_BIND_SERVICE" in unit
    password_tasks = [
        task
        for task in tasks
        if "password" in task["name"].lower() or "credential" in task["name"].lower()
    ]
    assert password_tasks
    assert all(task.get("no_log") is True for task in password_tasks)
