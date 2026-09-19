"""Read-only diagnostics for configured SSH/Torque environments."""

from __future__ import annotations

from typing import Any

from .client import SSHClient
from .errors import RemoteError
from .models import RemotePlatform
from .torque import parse_nodes, parse_records


MODES = frozenset({"status", "doctor", "queues", "nodes"})


def diagnose(mode: str, *, environment_name: str | None = None) -> dict[str, Any]:
    if mode not in MODES:
        raise RemoteError(f"unsupported compute environment diagnostic mode: {mode}")
    from ts_agent.platforms import load_config

    config = load_config()
    environment = config.environment(environment_name, kind="remote")
    platform = environment.platform
    if platform is None:
        raise RemoteError(f"compute environment has no remote platform: {environment.name}")
    client = SSHClient(platform)
    result: dict[str, Any] = {
        "schema_version": "compute-environment-diagnostic/1",
        "mode": mode,
        "environment": _environment_summary(environment.name, platform),
    }
    try:
        connection = client.run(["true"])
        result["connection"] = {"ok": connection.returncode == 0, "ssh_host": platform.ssh_host}
        if mode == "status":
            result["ok"] = True
            return result
        if mode in {"queues", "doctor"}:
            result["queues"] = _queues(client, platform)
        if mode in {"nodes", "doctor"}:
            result["nodes"] = _nodes(client, platform)
        if mode == "doctor":
            result["checks"] = _doctor(client, platform)
        result["ok"] = result.get("checks", {}).get("ok", True)
        return result
    except Exception as exc:
        result["ok"] = False
        result["error"] = {"class": type(exc).__name__, "message": str(exc)[:2000]}
        return result


def _queues(client: SSHClient, platform: RemotePlatform) -> list[dict[str, Any]]:
    output = client.run([platform.commands.qstat, "-Qf"]).stdout
    return [
        {
            "name": name,
            "allowed_for_submission": name in platform.allowed_queues,
            "enabled": raw.get("enabled"),
            "started": raw.get("started"),
            "total_jobs": _number_or_text(raw.get("total_jobs")),
            "state_count": raw.get("state_count"),
        }
        for name, raw in sorted(parse_records(output, "Queue").items())
    ]


def _nodes(client: SSHClient, platform: RemotePlatform) -> list[dict[str, Any]]:
    output = client.run([platform.commands.pbsnodes, "-a"]).stdout
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


def _doctor(client: SSHClient, platform: RemotePlatform) -> dict[str, Any]:
    root = client.run(["test", "-d", platform.remote_root, "-a", "-w", platform.remote_root], check=False)
    version = client.run([platform.commands.qstat, "--version"], check=False)
    backends: dict[str, Any] = {}
    for name, item in sorted(platform.backends.items()):
        executable = item.command[0]
        command_check = client.run_script(
            _backend_check_script(),
            [item.activation_script or "", executable],
            check=False,
        )
        dependency_check = None
        if name == "ase_neb":
            dependency_check = client.run_script(
                _ase_neb_check_script(),
                [
                    item.activation_script or "",
                    executable,
                    item.environment.get("TS_ASE_NEB_XTB", "xtb"),
                ],
                check=False,
            )
        activation_check = (
            client.run(["test", "-r", item.activation_script], check=False)
            if item.activation_script
            else None
        )
        backends[name] = {
            "command_available": command_check.returncode == 0,
            "activation_script_available": activation_check.returncode == 0 if activation_check else None,
            "runtime_dependencies_available": (
                dependency_check.returncode == 0 if dependency_check else None
            ),
            "allowed_queues": list(item.allowed_queues),
            "requires_gpu": item.requires_gpu,
        }
    checks = {
        "remote_root_writable": root.returncode == 0,
        "scheduler": "torque",
        "scheduler_version": (version.stdout or version.stderr).strip(),
        "backends": backends,
    }
    checks["ok"] = checks["remote_root_writable"] and all(
        item["command_available"]
        and item["activation_script_available"] is not False
        and item["runtime_dependencies_available"] is not False
        for item in backends.values()
    )
    return checks


def _backend_check_script() -> str:
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


def _ase_neb_check_script() -> str:
    return r'''set -eo pipefail
activation=$1
python_executable=$2
xtb_executable=$3
if [[ -n "$activation" ]]; then source "$activation"; fi
"$python_executable" -c 'import ase, numpy; import ts_agent.backends.ase_neb_runner'
if [[ "$xtb_executable" == /* ]]; then
  test -x "$xtb_executable"
else
  command -v -- "$xtb_executable" >/dev/null
fi
"$xtb_executable" --version >/dev/null 2>&1
'''


def _environment_summary(name: str, platform: RemotePlatform) -> dict[str, Any]:
    return {
        "name": name,
        "ssh_host": platform.ssh_host,
        "scheduler": platform.scheduler,
        "remote_root": platform.remote_root,
        "allowed_queues": list(platform.allowed_queues),
        "max_nodes": platform.max_nodes,
    }


def _number_or_text(value: object) -> object:
    return int(value) if isinstance(value, str) and value.isdigit() else value
