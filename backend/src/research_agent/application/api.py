"""Small canonical command service shared by CLI and host adapters.

The command names in this module are the public application boundary.  Pi
tools, slash commands, and CoRAgent Web are transports; they should not invent a
second research vocabulary of their own.
"""

from __future__ import annotations

import json
import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator



def _load_command_catalog() -> dict[str, Any]:
    value = json.loads(files("research_agent.application").joinpath("command_catalog.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != "coragent-command-catalog/1" or not isinstance(value.get("commands"), list):
        raise RuntimeError("invalid CoRAgent command catalog")
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
COMMAND_VALIDATORS = {command: Draft202012Validator(definition["schema"])
                      for command, definition in COMMAND_DEFINITIONS.items()}

class CommandError(ValueError):
    """A canonical command request is invalid or cannot be served."""


def _string(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise CommandError(f"{field} must be a non-empty string")
    return item.strip()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def validate_command_params(command: str, value: dict[str, Any], *, transport_fields: tuple[str, ...] = ()) -> None:
    """Reject retired/unknown fields using the catalog shared with JS transports."""
    if command not in COMMANDS:
        raise CommandError(f"unsupported command: {command}")
    if not isinstance(value, dict):
        raise CommandError("command params must be an object")
    if any(any(c.isupper() for c in key) for key in value):
        raise CommandError("schema_field_invalid: command fields use snake_case")
    unsupported = sorted(set(value) - set(COMMAND_DEFINITIONS[command]["allowed"]) - set(transport_fields))
    if unsupported:
        raise CommandError(f"schema_field_invalid: {command} unsupported fields: {', '.join(unsupported)}")
    required = COMMAND_DEFINITIONS[command].get("required", [])
    missing = [key for key in required if value.get(key) is None or value.get(key) == ""]
    if missing:
        raise CommandError(f"{command} requires {', '.join(missing)}")
    parameters = {key: item for key, item in value.items() if key not in transport_fields}
    error = next(COMMAND_VALIDATORS[command].iter_errors(parameters), None)
    if error is not None:
        location = ".".join(map(str, error.absolute_path)) or "parameters"
        raise CommandError(f"schema_field_invalid: {command} {location} violates {error.validator}")


def execute(command: str, root: str | Path, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a research, execution, or material command."""
    value = params if params is not None else {}
    validate_command_params(command, value)
    if command.startswith("research."):
        from research_agent.research import records, nodes, results, retrieval, basis, views
        from . import memory_context
        if command == "research.read":
            return memory_context.read(root, **value)
        if command == "research.search":
            return retrieval.search(root, **value)
        if command == "research.source":
            return records.record_source(root, value)
        if command == "research.observe":
            return basis.observe(root, value)
        mutations = {"research.create": nodes.create, "research.update": nodes.update, "research.result": results.publish}
        if command in mutations:
            from research_agent.foundation.transactions import TransactionCoordinator
            with TransactionCoordinator(root).locked():
                reply = mutations[command](root, {**value, "_reference_details": memory_context.reference_details(root, value)})
                try:
                    views.render(root)
                except (OSError, ValueError) as exc:
                    reply = {**reply, "view_error": str(exc)}
                return reply
        raise CommandError("unsupported research command")
    if command == "job.monitor_assess":
        from .job_monitor import assess
        return assess(root, **value)
    if command.startswith("job."):
        if command in {"job.prepare", "job.resolve_prepared"}:
            from research_agent.application.references import prepare_job, resolve_prepared_job
            return (prepare_job if command == "job.prepare" else resolve_prepared_job)(root, value)
        from research_agent.application.execution import dispatch
        return dispatch(command.removeprefix("job."), {**value, "workspace_root": str(root)})
    if command.startswith("artifact."):
        from research_agent.application.evidence import dispatch
        return dispatch(command.removeprefix("artifact."), {**value, "workspace_root": str(root)})
    raise CommandError(f"unsupported command family: {command}")
