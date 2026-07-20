"""Runtime Ansible inventory and guarded Debian-family baseline execution."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from homelabctl.configuration import find_project_root, load_config
from homelabctl.guard import OperationLockedError, mutation_lock
from homelabctl.progress import is_enabled as live_progress_enabled
from homelabctl.progress import report


class AnsibleError(RuntimeError):
    """Raised when inventory generation or baseline execution is unsafe."""


@dataclass(frozen=True, slots=True)
class AnsibleResult:
    changed: bool
    inventory_path: Path
    diagnostic_log: Path
    lines: tuple[str, ...]


def _paths(config_path: Path) -> tuple[Path, Path, Path]:
    root = find_project_root(config_path.parent)
    runtime = root / ".cache" / "ansible"
    runtime.mkdir(parents=True, exist_ok=True)
    return root, runtime / "inventory.json", root / "logs" / "ansible.log"


def _tofu_outputs(root: Path, tofu_executable: str | None = None) -> dict[str, object]:
    tofu = tofu_executable or shutil.which("tofu")
    if not tofu:
        raise AnsibleError("OpenTofu is not installed or not on PATH")
    environment = os.environ.copy()
    environment["TF_IN_AUTOMATION"] = "1"
    environment["TF_INPUT"] = "0"
    environment["TF_DATA_DIR"] = str(root / ".cache" / "tofu" / "data")
    completed = subprocess.run(
        [tofu, f"-chdir={root / 'infrastructure'}", "output", "-json", "proxmox_lxcs"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    if completed.returncode != 0:
        raise AnsibleError(
            "Unable to read provisioned guests from OpenTofu state. "
            "Apply the reviewed infrastructure plan first."
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AnsibleError("OpenTofu returned invalid guest inventory output") from exc
    if not isinstance(value, dict):
        raise AnsibleError("OpenTofu guest inventory output must be an object")
    return value


def generate_inventory(
    config_path: Path, *, tofu_executable: str | None = None
) -> tuple[Path, tuple[str, ...]]:
    config = load_config(config_path)
    root, inventory_path, _ = _paths(config_path)
    outputs = _tofu_outputs(root, tofu_executable)
    declared = {guest.key: guest for guest in config.proxmox.containers}
    if set(outputs) != set(declared):
        raise AnsibleError(
            "OpenTofu state does not match the configured guest set; create and review a new plan"
        )
    key_path = Path(config.automation.ssh_private_key).expanduser().resolve()
    if not key_path.is_file():
        raise AnsibleError(f"Guest automation SSH private key not found: {key_path}")
    hosts: dict[str, object] = {}
    summary: list[str] = []
    for key in sorted(outputs):
        guest = outputs[key]
        if not isinstance(guest, dict):
            raise AnsibleError(f"OpenTofu output for guest {key} is invalid")
        address = guest.get("management_address")
        hostname = guest.get("hostname")
        if not isinstance(address, str) or not isinstance(hostname, str):
            raise AnsibleError(f"OpenTofu output for guest {key} is incomplete")
        hosts[key] = {
            "ansible_host": address,
            "ansible_user": "root",
            "ansible_ssh_private_key_file": str(key_path),
            "homelab_hostname": hostname,
            "homelab_automation_user": config.automation.ssh_user,
            "homelab_timezone": config.site.timezone,
        }
        summary.append(f"{key}: root@{address} ({hostname})")
    known_hosts = root / ".cache" / "ansible" / "known_hosts"
    inventory = {
        "all": {
            "hosts": hosts,
            "vars": {
                "ansible_become": False,
                # Never leave a hidden SSH confirmation prompt behind the menu.
                # New host keys are recorded and changed keys still fail safely.
                "ansible_ssh_common_args": (
                    f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known_hosts}"
                ),
            },
        }
    }
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    with suppress(OSError):
        os.chmod(inventory_path, 0o600)
    return inventory_path, tuple(summary)


def _run_ansible_with_live_output(
    command: list[str],
    root: Path,
    diagnostic: Path,
    *,
    timeout_seconds: int = 300,
    environment_updates: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run Ansible with live output and a firm operation deadline."""

    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["ANSIBLE_NOCOLOR"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    environment.update(environment_updates or {})
    output: list[str] = []
    try:
        with (
            subprocess.Popen(
                command,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=environment,
            ) as process,
            diagnostic.open("w", encoding="utf-8", newline="\n") as log,
        ):
            assert process.stdout is not None
            output_queue: Queue[str | None] = Queue()

            def read_output() -> None:
                for raw_line in process.stdout:
                    output_queue.put(raw_line)
                output_queue.put(None)

            reader = Thread(target=read_output, name="homelab-ansible-output", daemon=True)
            reader.start()
            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise AnsibleError(
                        "Ansible operation stopped after "
                        f"{timeout_seconds} seconds. Review {diagnostic}; the last displayed "
                        "task identifies where it stopped."
                    )
                try:
                    raw_line = output_queue.get(timeout=min(remaining, 1))
                except Empty:
                    continue
                if raw_line is None:
                    break
                line = raw_line.rstrip("\r\n")
                output.append(line)
                log.write(line + "\n")
                log.flush()
                if line:
                    report(line)
            returncode = process.wait()
    except OSError as exc:
        raise AnsibleError(f"Unable to start Ansible: {exc}") from exc
    return subprocess.CompletedProcess(command, returncode, "\n".join(output), "")


def run_baseline(
    config_path: Path,
    *,
    check: bool,
    tofu_executable: str | None = None,
    ansible_executable: str | None = None,
) -> AnsibleResult:
    root, _, diagnostic = _paths(config_path)
    inventory, hosts = generate_inventory(config_path, tofu_executable=tofu_executable)
    if not hosts:
        raise AnsibleError("No provisioned guests are configured for baseline management")
    ansible = ansible_executable or shutil.which("ansible-playbook")
    if not ansible:
        raise AnsibleError("ansible-playbook is not installed or not on PATH")
    command = [
        ansible,
        "-i",
        str(inventory),
        str(root / "ansible" / "baseline.yml"),
        "--diff",
        "--timeout",
        "30",
    ]
    if check:
        command.append("--check")
    try:
        if live_progress_enabled():
            if check:
                completed = _run_ansible_with_live_output(command, root, diagnostic)
            else:
                with mutation_lock(root, "Ansible baseline apply"):
                    completed = _run_ansible_with_live_output(command, root, diagnostic)
        elif check:
            completed = subprocess.run(
                command,
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        else:
            with mutation_lock(root, "Ansible baseline apply"):
                completed = subprocess.run(
                    command,
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
    except OperationLockedError as exc:
        raise AnsibleError(str(exc)) from exc
    if not live_progress_enabled():
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        safe_output = "\n".join((completed.stdout, completed.stderr)).strip()
        diagnostic.write_text(safe_output + "\n", encoding="utf-8")
    if completed.returncode != 0:
        raise AnsibleError(f"Ansible baseline failed; review the sanitized log at {diagnostic}")
    recap = tuple(
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip().startswith(tuple(host.split(":", 1)[0] for host in hosts))
    )
    return AnsibleResult(
        changed="changed=0" not in completed.stdout,
        inventory_path=inventory,
        diagnostic_log=diagnostic,
        lines=recap or hosts,
    )
