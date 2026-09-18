"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and TS Web are transports; they should not invent a
second research-state vocabulary of their own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .research import ResearchKernel


RESEARCH_COMMANDS = frozenset({
    "research.map",
    "research.summary",
    "research.detail",
    "research.locate",
    "research.validate",
    "research.operations",
    "research.change",
})
COMPUTE_COMMANDS = frozenset({
    "compute.environments",
    "compute.environment",
    "compute.capabilities",
    "compute.artifacts",
    "compute.runs",
})
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
        return {
            "schema_version": "research-operation-catalog/1",
            "operations": [
                {"type": name, "description": description}
                for name, description in _RESEARCH_OPERATIONS
            ],
        }
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
        item = next((profile for profile in catalog["environments"] if profile["name"] == name), None)
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
        from .workspace.operational import operational_snapshot

        snapshot = operational_snapshot(root)
        return {
            "schema_version": "compute-runs/1",
            "runs": snapshot.get("agent_runs", []),
            "attempts": snapshot.get("calculation_attempts", []),
            "summary": snapshot.get("operational_summary", {}),
        }
    raise CommandError(f"unsupported compute command: {action}")


def _environment_catalog() -> dict[str, Any]:
    from .compute.config import ComputeConfigurationError, load_config

    try:
        config = load_config()
    except ComputeConfigurationError as exc:
        return {
            "schema_version": "compute-environment-catalog/1",
            "configured": False,
            "error": str(exc),
            "default": None,
            "environments": [],
        }
    profiles = []
    for profile in sorted(config.profiles.values(), key=lambda item: item.name):
        remote = profile.remote
        profiles.append({
            "name": profile.name,
            "kind": profile.kind,
            "default": profile.name == config.default_profile,
            "software": {
                backend: {
                    "command": list(provider.command),
                    "activation_script": provider.activation_script,
                    "scratch_root": provider.scratch_root,
                    "environment_keys": sorted(provider.environment),
                }
                for backend, provider in sorted(profile.software.items())
            },
            "remote": {
                "ssh_host": remote.ssh_host,
                "scheduler": remote.scheduler,
                "remote_root": remote.remote_root,
                "allowed_queues": list(remote.allowed_queues),
                "max_nodes": remote.max_nodes,
            } if remote else None,
        })
    return {
        "schema_version": "compute-environment-catalog/1",
        "configured": True,
        "source": str(config.source),
        "default": config.default_profile,
        "environments": profiles,
    }


_RESEARCH_OPERATIONS = (
    ("create_phase", "add a ResearchPhase"),
    ("create_claim", "add a ResearchClaim"),
    ("create_node", "add a ResearchNode"),
    ("create_finding", "record a Finding produced by a ResearchNode"),
    ("create_gate", "add a Gate for a node or claim"),
    ("evaluate_gate", "append a Gate evaluation"),
    ("set_node_state", "transition a ResearchNode"),
    ("set_claim_status", "change a ResearchClaim status"),
    ("relate_claims", "add a directed claim relation"),
    ("set_focus", "set the map focus"),
)


def _string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"{key} must be a non-empty string")
    return value.strip()


def _json_text(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = ["COMMANDS", "COMPUTE_COMMANDS", "CommandError", "RESEARCH_COMMANDS", "execute"]
