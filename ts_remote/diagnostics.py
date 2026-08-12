"""Read-only diagnostics for configured SSH/Torque profiles."""

from __future__ import annotations

from typing import Any

from .client import SSHClient
from .config import load_config
from .errors import RemoteError
from .models import RemoteProfile
from .torque import parse_nodes, parse_records


MODES = frozenset({"status", "doctor", "queues", "nodes", "cluster"})


def diagnose(mode: str, *, profile_name: str | None = None) -> dict[str, Any]:
    if mode not in MODES:
        raise RemoteError(f"unsupported ts_remote diagnostic mode: {mode}")
    config = load_config()
    profile = config.profile(profile_name or config.default_profile)
    client = SSHClient(profile)
    result: dict[str, Any] = {
        "schema_version": "ts-remote-diagnostic/1",
        "mode": mode,
        "profile": _profile_summary(profile),
    }
    try:
        connection = client.run(["true"])
        result["connection"] = {"ok": connection.returncode == 0, "ssh_host": profile.ssh_host}
        if mode == "status":
            result["ok"] = True
            return result
        if mode in {"queues", "cluster", "doctor"}:
            result["queues"] = _queues(client, profile)
        if mode in {"nodes", "cluster", "doctor"}:
            result["nodes"] = _nodes(client, profile)
        if mode in {"doctor", "cluster"}:
            result["checks"] = _doctor(client, profile)
        result["ok"] = result.get("checks", {}).get("ok", True)
        return result
    except Exception as exc:
        result["ok"] = False
        result["error"] = {"class": type(exc).__name__, "message": str(exc)[:2000]}
        return result


def _queues(client: SSHClient, profile: RemoteProfile) -> list[dict[str, Any]]:
    output = client.run([profile.commands.qstat, "-Qf"]).stdout
    return [
        {
            "name": name,
            "allowed_for_submission": name in profile.allowed_queues,
            "enabled": raw.get("enabled"),
            "started": raw.get("started"),
            "total_jobs": _number_or_text(raw.get("total_jobs")),
            "state_count": raw.get("state_count"),
        }
        for name, raw in sorted(parse_records(output, "Queue").items())
    ]


def _nodes(client: SSHClient, profile: RemoteProfile) -> list[dict[str, Any]]:
    output = client.run([profile.commands.pbsnodes, "-a"]).stdout
    return [
        {
            "name": name,
            "state": raw.get("state"),
            "np": _number_or_text(raw.get("np")),
            "properties": [item.strip() for item in raw.get("properties", "").split(",") if item.strip()],
            "jobs": raw.get("jobs"),
        }
        for name, raw in sorted(parse_nodes(output).items())
    ]


def _doctor(client: SSHClient, profile: RemoteProfile) -> dict[str, Any]:
    root = client.run(["test", "-d", profile.remote_root, "-a", "-w", profile.remote_root], check=False)
    version = client.run([profile.commands.qstat, "--version"], check=False)
    software: dict[str, Any] = {}
    for name, item in sorted(profile.software.items()):
        executable = item.command[0]
        command_check = client.run_script(
            _software_check_script(),
            [item.activation_script or "", executable],
            check=False,
        )
        activation_check = (
            client.run(["test", "-r", item.activation_script], check=False)
            if item.activation_script
            else None
        )
        software[name] = {
            "command_available": command_check.returncode == 0,
            "activation_script_available": activation_check.returncode == 0 if activation_check else None,
            "allowed_queues": list(item.allowed_queues),
            "requires_gpu": item.requires_gpu,
        }
    checks = {
        "remote_root_writable": root.returncode == 0,
        "scheduler": "torque",
        "scheduler_version": (version.stdout or version.stderr).strip(),
        "software": software,
    }
    checks["ok"] = checks["remote_root_writable"] and all(
        item["command_available"] and item["activation_script_available"] is not False
        for item in software.values()
    )
    return checks


def _software_check_script() -> str:
    return r'''set -eo pipefail
activation=$1
executable=$2
if [[ -n "$activation" ]]; then source "$activation"; fi
if [[ "$executable" == /* ]]; then
  test -x "$executable"
else
  command -v -- "$executable" >/dev/null
fi
'''


def _profile_summary(profile: RemoteProfile) -> dict[str, Any]:
    return {
        "name": profile.name,
        "ssh_host": profile.ssh_host,
        "scheduler": profile.scheduler,
        "remote_root": profile.remote_root,
        "allowed_queues": list(profile.allowed_queues),
        "max_nodes": profile.max_nodes,
    }


def _number_or_text(value: object) -> object:
    return int(value) if isinstance(value, str) and value.isdigit() else value
