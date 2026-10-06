"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and TS Web are transports; they should not invent a
second research-state vocabulary of their own.
"""

from __future__ import annotations

import json
import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Any

from research_state.operation_registry import operation_catalog
from research_state.projection import research_map_document, research_summary_document
from tspi_foundation.io import sha256_json


def _load_command_catalog() -> dict[str, Any]:
    value = json.loads(files("tspi_runtime").joinpath("command_catalog.json").read_text(encoding="utf-8"))
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
COMMANDS = frozenset(COMMAND_DEFINITIONS)

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
        # The filesystem Research Agent protocol is the only public research
        # workspace path. The retired JSON/SQLite implementation is not a
        # fallback and cannot be selected by the public command service.
        from research_state.agent_workspace import dispatch as dispatch_agent_workspace, has_partial_state_files, has_state_files

        if not has_state_files(root) and not has_partial_state_files(root):
            raise CommandError(
                "research commands require an initialized filesystem Research Agent workspace"
            )
        action = command.removeprefix("research.")
        request = value.get("request") if isinstance(value.get("request"), dict) else value
        method = {
            "context": "read_context",
            "map": "read_context",
            "summary": "read_context",
            "liveness": "read_liveness",
            "validate": "read_context",
            "turn": "turn",
            "change": "apply_change",
            "checkpoint": "checkpoint",
        }.get(action)
        if method is not None:
            result = dispatch_agent_workspace(root, method, request)
            # Native Host and the Python command transport expose the same
            # checkpoint/liveness envelope. A checkpoint writes the durable
            # projection first; read it back so callers never have to infer
            # lifecycle state from the mutation receipt alone.
            if action == "checkpoint" or (action == "turn" and request.get("operation") == "checkpoint"):
                liveness = dispatch_agent_workspace(root, "read_liveness", request)
                return {
                    **result,
                    "lifecycle": liveness.get("lifecycle"),
                    "disposition": liveness.get("disposition"),
                    "liveness": liveness,
                }
            if action == "map":
                return research_map_document(result)
            if action == "summary":
                return research_summary_document(result)
            if action == "validate":
                return {"schema_version": "research-validation/1", "valid": True, "revision": result.get("revision")}
            return result
        if action in {"strategy", "interpretation"}:
            return _filesystem_decision(root, action, request, dispatch_agent_workspace)
        if action in {"detail", "locate", "operations", "decisions", "evidence", "storage"}:
            context = dispatch_agent_workspace(root, "read_context", request)
            if action == "operations":
                return operation_catalog()
            if action == "storage":
                operation = value.get("operation", "status")
                if operation != "status":
                    raise CommandError("research.storage supports only operation=status")
                return {
                    "schema_version": "research-storage/1",
                    "backend": "filesystem",
                    "sqlite": False,
                    "path": str(Path(root) / "research_map" / "context.json"),
                    "revision": context.get("revision", 0),
                }
            if action == "detail":
                kind = _string(value, "kind")
                identifier = _string(value, "id")
                collection = {"phase": "phases", "claim": "claims", "node": "nodes", "finding": "findings", "gate": "gates"}.get(kind)
                if collection is None:
                    raise CommandError("research.detail kind must be phase, claim, node, finding, or gate")
                item = next((row for row in context.get(collection, []) if row.get("id") == identifier), None)
                if item is None:
                    raise CommandError(f"unknown {kind} id: {identifier}")
                # Native Host and Python command transports expose the same
                # detail envelope. ``item`` is the canonical record field;
                # callers must not branch on a transport-specific ``object``
                # alias or depend on an incidental map_id projection.
                return {"schema_version": "research-detail/1", "kind": kind, "id": identifier, "item": item}
            if action == "locate":
                query = _string(value, "query").casefold()
                matches = []
                for collection in ("phases", "claims", "nodes", "findings", "gates"):
                    for item in context.get(collection, []):
                        if query in _json_text(item).casefold():
                            matches.append({**item, "collection": collection[:-1], "object_type": item.get("type", collection[:-1])})
                return {"schema_version": "research-locate/1", "map_id": research_map_document(context)["map_id"], "matches": matches}
            if action == "decisions":
                claim_id = value.get("claim_id") or value.get("claimId")
                records = [
                    *[{**item, "decision_type": "strategy_plan"} for item in context.get("strategy_plans", [])],
                    *[{**item, "decision_type": "strategy_review"} for item in context.get("strategy_reviews", [])],
                    *[{**item, "decision_type": "attempt_interpretation"} for item in context.get("attempt_interpretations", [])],
                ]
                if claim_id is not None:
                    records = [item for item in records if item.get("claim_id") == claim_id]
                limit = value.get("limit", 128)
                if type(limit) is not int or not 1 <= limit <= 2048:
                    raise CommandError("research.decisions limit must be an integer between 1 and 2048")
                return {"schema_version": "research-decisions/1", "claim_id": claim_id, "records": records[:limit]}
            record_type = value.get("record_type") or value.get("recordType")
            groups = {"attempt": "attempts", "artifact": "artifacts", "link": "evidence_links"}
            if record_type is not None and record_type not in groups:
                raise CommandError("research.evidence record_type must be attempt, artifact, or link")
            names = [groups[record_type]] if record_type in groups else list(groups.values())
            records = [item for name in names for item in context.get(name, [])]
            filters = {
                "node_id": value.get("node_id") or value.get("nodeId"),
                "artifact_id": value.get("artifact_id") or value.get("artifactId"),
                "subject_id": value.get("subject_id") or value.get("subjectId"),
            }
            for field, expected in filters.items():
                if expected is None:
                    continue
                records = [
                    item for item in records
                    if item.get(field) == expected
                    or (isinstance(item.get("subject"), dict) and item["subject"].get(field) == expected)
                    or (isinstance(item.get(f"{field}s"), list) and expected in item[f"{field}s"])
                ]
            limit = value.get("limit", 128)
            if type(limit) is not int or not 1 <= limit <= 2048:
                raise CommandError("research.evidence limit must be an integer between 1 and 2048")
            return {"schema_version": "research-evidence/1", "record_type": record_type, "records": records[:limit]}
        raise CommandError(
            f"research.{action} is served by the Host Research State filesystem boundary; use the native command boundary"
        )
    if command.startswith("job."):
        from tspi_runtime.execution import dispatch
        return dispatch(command.removeprefix("job."), {**value, "workspace_root": str(root)})
    if command.startswith("artifact."):
        from tspi_runtime.evidence import dispatch
        return dispatch(command.removeprefix("artifact."), {**value, "workspace_root": str(root)})
    raise CommandError(f"unsupported command family: {command}")


def _filesystem_decision(root: str | Path, action: str, request: dict[str, Any], dispatch: Any) -> dict[str, Any]:
    """Apply the same typed strategy/interpretation envelope as Native Host."""

    operation_name = request.get("operation")
    if action == "strategy":
        source = request.get(operation_name) if isinstance(operation_name, str) else None
        source = source or request.get("plan") or request.get("review") or request.get("strategy")
        operation_type = "create_strategy_review" if operation_name == "review" else "create_strategy_plan"
    else:
        source = request.get("interpretation")
        operation_type = "create_interpretation"
    if not isinstance(source, dict) or isinstance(source, list):
        raise CommandError(f"research.{action} requires a decision object")
    change_request = {
        **request,
        "operations": [{"type": operation_type, **source}],
    }
    commit = dispatch(root, "apply_change", change_request)
    return {
        "schema_version": f"research-{action}-result/1",
        "operation": operation_name or action,
        "record": source,
        "commit": commit,
    }
