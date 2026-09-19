"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and TS Web are transports; they should not invent a
second research-state vocabulary of their own.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from .research import ResearchKernel
from .workspace.operation_registry import operation_catalog


def _load_command_catalog() -> dict[str, Any]:
    value = json.loads(files("ts_agent").joinpath("command_catalog.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != "tspi-command-catalog/1" or not isinstance(value.get("commands"), list):
        raise RuntimeError("invalid TSPi command catalog")
    return value


COMMAND_CATALOG = _load_command_catalog()
COMMAND_DEFINITIONS = {
    str(item["id"]): item
    for item in COMMAND_CATALOG["commands"]
    if isinstance(item, dict) and isinstance(item.get("id"), str)
}
RESEARCH_COMMANDS = frozenset(
    command for command, definition in COMMAND_DEFINITIONS.items() if definition.get("domain") == "research"
)
COMPUTE_COMMANDS = frozenset(
    command for command, definition in COMMAND_DEFINITIONS.items() if definition.get("domain") == "compute"
)
COMMANDS = RESEARCH_COMMANDS | COMPUTE_COMMANDS


class CommandError(ValueError):
    """A canonical command request is invalid or cannot be served."""


def execute(command: str, root: str | Path, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute one read/query command or one explicit ResearchMap change."""

    if command not in COMMANDS:
        raise CommandError(f"unsupported command: {command}")
    value = params if params is not None else {}
    if not isinstance(value, dict):
        raise CommandError("command params must be an object")
    required = COMMAND_DEFINITIONS[command].get("required", [])
    missing = [key for key in required if value.get(key) is None or value.get(key) == ""]
    if missing:
        raise CommandError(f"{command} requires {', '.join(missing)}")
    if command.startswith("research."):
        return _research(command.removeprefix("research."), root, value)
    return _compute(command.removeprefix("compute."), root, value)


def _research(action: str, root: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    kernel = ResearchKernel(root)
    if action == "map":
        return kernel.load().to_dict()
    if action == "summary":
        research_map = kernel.load()
        return {
            "schema_version": "research-summary/1",
            "map_id": research_map.map_id,
            "title": research_map.title,
            "revision": research_map.revision,
            "progress": research_map.progress(),
            "ready_node_ids": [node.id for node in research_map.ready_nodes()],
            "focus_claim_ids": list(research_map.focus_claim_ids),
            "focus_node_ids": list(research_map.focus_node_ids),
        }
    if action == "validate":
        kernel.load()
        return {"schema_version": "research-validation/1", "valid": True}
    if action == "operations":
        return operation_catalog()
    if action == "detail":
        research_map = kernel.load().to_dict()
        kind = _string(params, "kind")
        identifier = _string(params, "id")
        collection = {
            "phase": "phases",
            "claim": "claims",
            "node": "nodes",
            "finding": "findings",
            "gate": "gates",
        }.get(kind)
        if collection is None:
            raise CommandError("research.detail kind must be phase, claim, node, finding, or gate")
        item = next((row for row in research_map[collection] if row.get("id") == identifier), None)
        if item is None:
            raise CommandError(f"unknown {kind} id: {identifier}")
        return {"schema_version": "research-detail/1", "map_id": research_map["map_id"], "object": item}
    if action == "locate":
        query = _string(params, "query").casefold()
        research_map = kernel.load().to_dict()
        matches = []
        for collection in ("phases", "claims", "nodes", "findings", "gates"):
            kind = collection[:-1]
            for item in research_map[collection]:
                if query in _json_text(item).casefold():
                    matches.append({**item, "collection": kind, "object_type": item.get("type", kind)})
        return {"schema_version": "research-locate/1", "map_id": research_map["map_id"], "matches": matches}
    if action == "change":
        request = params.get("request")
        if not isinstance(request, dict):
            raise CommandError("research.change requires params.request")
        return kernel.apply(request)
    raise CommandError(f"unsupported research command: {action}")


def _compute(action: str, root: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    if action == "environments":
        return _environment_catalog()
    if action == "environment":
        name = _string(params, "name")
        catalog = _environment_catalog()
        item = next((environment for environment in catalog["environments"] if environment["name"] == name), None)
        if item is None:
            raise CommandError(f"unknown compute environment: {name}")
        return {"schema_version": "compute-environment/1", "environment": item}
    if action == "capabilities":
        from .compute.capabilities import calculation_capabilities

        return calculation_capabilities()
    if action == "artifacts":
        from .compute.artifacts import list_calculation_artifacts

        return list_calculation_artifacts(root, node_id=params.get("node_id"))
    if action == "runs":
        from .workspace.operational import runtime_status

        status = runtime_status(root)
        return {
            "schema_version": "compute-runs/1",
            "runs": status.get("agent_runs", []),
            "attempts": status.get("calculation_attempts", []),
            "summary": status.get("runtime_summary", {}),
        }
    raise CommandError(f"unsupported compute command: {action}")


def _environment_catalog() -> dict[str, Any]:
    from .platforms import EnvironmentConfigurationError, load_config

    try:
        config = load_config()
    except EnvironmentConfigurationError as exc:
        return {
            "schema_version": "compute-environment-catalog/1",
            "configured": False,
            "error": str(exc),
            "default": None,
            "environments": [],
        }
    environments = []
    for environment in sorted(config.environments.values(), key=lambda item: item.name):
        platform = environment.platform
        environments.append({
            "name": environment.name,
            "kind": environment.kind,
            "default": environment.name == config.default_environment,
            "backends": {
                backend: {
                    "command": list(binding.command),
                    "activation_script": binding.activation_script,
                    "scratch_root": binding.scratch_root,
                    "environment_keys": sorted(binding.environment),
                }
                for backend, binding in sorted(environment.backends.items())
            },
            "platform": {
                "kind": "ssh_torque",
                "ssh_host": platform.ssh_host,
                "scheduler": platform.scheduler,
                "remote_root": platform.remote_root,
                "allowed_queues": list(platform.allowed_queues),
                "max_nodes": platform.max_nodes,
            } if platform else {"kind": "local"},
        })
    return {
        "schema_version": "compute-environment-catalog/1",
        "configured": True,
        "source": str(config.source),
        "default": config.default_environment,
        "environments": environments,
    }


def _string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{key} must be a non-empty string")
    return value.strip()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "COMMAND_CATALOG",
    "COMMAND_DEFINITIONS",
    "COMMANDS",
    "COMPUTE_COMMANDS",
    "CommandError",
    "RESEARCH_COMMANDS",
    "execute",
]
