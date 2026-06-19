"""Optional pathway-level aggregation for multi-step TS searches."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import PATHWAY_MODEL_SCHEMA, derive_node_audit_view
from transition_state_workflow.util.json_io import read_json_object_optional, read_json_object_required, write_json_object
from transition_state_workflow.util.path_utils import clean_string, list_or_empty, safe_identifier_token


PATHWAY_MODES = {"unknown", "single_step", "multi_step"}
PATHWAY_STATUSES = {"hypothesis", "partial", "complete", "rejected", "ambiguous"}
STEP_STATUSES = {"missing", "candidate", "accepted_ts", "ambiguous", "rejected"}


def pathway_model_path(root: Path) -> Path:
    """Return the pathway model path for a workspace root."""

    return root / "pathway_model.json"


def default_pathway_model(*, system: str, mode: str, timestamp: str) -> dict[str, Any]:
    """Build an empty pathway model."""

    validate_pathway_mode(mode)
    return {
        "schema": PATHWAY_MODEL_SCHEMA,
        "system": system,
        "mode": mode,
        "active_pathway": "",
        "pathways": [],
        "updated_at": timestamp,
    }


def build_initial_pathway_model(
    *,
    system: str,
    timestamp: str,
    mode: str = "unknown",
    pathway_id: str = "",
    pathway_label: str = "",
    step_specs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return the initial pathway model requested by ``init_workspace``."""

    mode = clean_string(mode) or "unknown"
    validate_pathway_mode(mode)
    pathway_id = safe_identifier_token(pathway_id) if clean_string(pathway_id) else ""
    pathway_label = clean_string(pathway_label)
    steps = [parse_step_spec(item) for item in step_specs]
    validate_unique_step_ids(steps)
    if step_specs and mode != "multi_step":
        raise SystemExit("--pathway-step requires --pathway-mode multi_step")
    if mode == "multi_step":
        if not pathway_id:
            raise SystemExit("--pathway-mode multi_step requires --pathway-id")
        if not steps:
            raise SystemExit("--pathway-mode multi_step requires at least one --pathway-step")
    elif pathway_id:
        raise SystemExit("--pathway-id is only valid with --pathway-mode multi_step")
    elif pathway_label:
        raise SystemExit("--pathway-label is only valid with --pathway-mode multi_step")
    model = default_pathway_model(system=system, mode=mode, timestamp=timestamp)
    if not pathway_id:
        return model
    model["active_pathway"] = pathway_id
    model["pathways"] = [
        {
            "pathway_id": pathway_id,
            "label": pathway_label or default_pathway_label(steps),
            "status": derive_pathway_status(steps),
            "steps": steps,
            "updated_at": timestamp,
        }
    ]
    return model


def validate_pathway_mode(mode: str) -> None:
    """Reject pathway modes outside the public contract."""

    if mode not in PATHWAY_MODES:
        raise SystemExit(f"invalid pathway mode: {mode}")


def default_pathway_label(steps: list[dict[str, Any]]) -> str:
    """Derive a readable pathway label from the initialized step boundaries."""

    if not steps:
        return ""
    first = clean_string(steps[0].get("from"))
    last = clean_string(steps[-1].get("to"))
    if first and last:
        return f"{first} to {last}"
    return "Initialized pathway"


def bind_pathway_step_to_accepted_ts(
    *,
    root: Path,
    pathway_id: str,
    step_id: str,
    node_id: str,
    timestamp: str,
    require_node_claim: bool,
) -> None:
    """Bind one accepted TS node to one pathway step and update node metadata."""

    pathway_id = clean_string(pathway_id)
    step_id = clean_string(step_id)
    node_id = clean_string(node_id)
    if not pathway_id or not step_id or not node_id:
        raise SystemExit("pathway binding requires --pathway-id, --step-id, and --node-id")
    node_path = root / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise SystemExit(f"pathway accepted_ts node does not exist: {node_id}")
    node_payload = read_json_object_required(node_path)
    node_audit = derive_node_audit_view(node_payload)
    if require_node_claim and clean_string(node_audit.get("claim_status")) != "accepted_ts":
        raise SystemExit("pathway-bind-step requires a node with claim_status=accepted_ts")
    model = read_pathway_model_required(root)
    pathway = find_pathway(model, pathway_id)
    step = find_step(pathway, step_id)
    node_pathway_id = clean_string(node_payload.get("pathway_id"))
    node_step_id = clean_string(node_payload.get("elementary_step_id"))
    if (node_pathway_id or node_step_id) and (node_pathway_id != pathway_id or node_step_id != step_id):
        raise SystemExit(
            "accepted_ts node is already bound to a different pathway step: "
            f"{node_pathway_id}:{node_step_id}"
        )
    existing_node = clean_string(step.get("accepted_ts_node"))
    if existing_node and existing_node != node_id:
        raise SystemExit(f"pathway step is already bound to accepted_ts node: {existing_node}")
    for other_pathway in list_or_empty(model.get("pathways")):
        if not isinstance(other_pathway, dict):
            continue
        other_pathway_id = clean_string(other_pathway.get("pathway_id"))
        for other_step in list_or_empty(other_pathway.get("steps")):
            if not isinstance(other_step, dict):
                continue
            if other_pathway_id == pathway_id and clean_string(other_step.get("step_id")) == step_id:
                continue
            if clean_string(other_step.get("accepted_ts_node")) == node_id:
                raise SystemExit(
                    "accepted_ts node is already assigned to another pathway step: "
                    f"{other_pathway_id}:{clean_string(other_step.get('step_id'))}"
                )
    step["status"] = "accepted_ts"
    step["accepted_ts_node"] = node_id
    step["updated_at"] = timestamp
    step["evidence_refs"] = evidence_refs_for_node(root, node_id)
    pathway["status"] = derive_pathway_status(list_or_empty(pathway.get("steps")))
    model["active_pathway"] = pathway_id
    model["updated_at"] = timestamp
    node_payload["pathway_id"] = pathway_id
    node_payload["elementary_step_id"] = step_id
    node_payload["intended_reaction_boundary"] = {
        "from": clean_string(step.get("from")),
        "to": clean_string(step.get("to")),
    }
    write_json_object(node_path, node_payload, overwrite_existing=True)
    write_json_object(pathway_model_path(root), model, overwrite_existing=True)


def bind_pathway_audit_node(
    *,
    root: Path,
    pathway_id: str,
    node_id: str,
    timestamp: str,
) -> None:
    """Bind a pathway-level audit node to a complete multi-step pathway."""

    pathway_id = clean_string(pathway_id)
    node_id = clean_string(node_id)
    if not pathway_id or not node_id:
        raise SystemExit("pathway audit binding requires --pathway-id and --node-id")
    node_path = root / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise SystemExit(f"pathway audit node does not exist: {node_id}")
    model = read_pathway_model_required(root)
    pathway = find_pathway(model, pathway_id)
    steps = [step for step in list_or_empty(pathway.get("steps")) if isinstance(step, dict)]
    if derive_pathway_status(steps) != "complete":
        raise SystemExit("accepted_pathway requires every pathway step to be bound to an accepted_ts node")
    existing_node = clean_string(pathway.get("accepted_pathway_audit_node"))
    if existing_node and existing_node != node_id:
        raise SystemExit(f"pathway already has accepted_pathway_audit_node: {existing_node}")
    pathway["status"] = "complete"
    pathway["accepted_pathway_audit_node"] = node_id
    pathway["updated_at"] = timestamp
    model["active_pathway"] = pathway_id
    model["updated_at"] = timestamp

    node_payload = read_json_object_required(node_path)
    node_payload["pathway_id"] = pathway_id
    node_payload.pop("elementary_step_id", None)
    node_payload["pathway_audit"] = {
        "pathway_id": pathway_id,
        "status": "complete",
        "accepted_step_nodes": [
            clean_string(step.get("accepted_ts_node"))
            for step in steps
            if clean_string(step.get("accepted_ts_node"))
        ],
    }
    write_json_object(node_path, node_payload, overwrite_existing=True)
    write_json_object(pathway_model_path(root), model, overwrite_existing=True)


def mark_pathway_step_status(
    *,
    root: Path,
    pathway_id: str,
    step_id: str,
    status: str,
    node_id: str,
    evidence_refs: list[str],
    timestamp: str,
) -> None:
    """Mark one pathway step as candidate, ambiguous, or rejected."""

    pathway_id = clean_string(pathway_id)
    step_id = clean_string(step_id)
    node_id = clean_string(node_id)
    status = clean_string(status)
    if status not in {"candidate", "ambiguous", "rejected"}:
        raise SystemExit(f"invalid pathway step status for mark operation: {status}")
    if not pathway_id or not step_id or not node_id:
        raise SystemExit("pathway step status update requires pathway_id, step_id, and node_id")
    node_path = root / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise SystemExit(f"pathway status node does not exist: {node_id}")
    model = read_pathway_model_required(root)
    pathway = find_pathway(model, pathway_id)
    step = find_step(pathway, step_id)
    existing_accepted = clean_string(step.get("accepted_ts_node"))
    if existing_accepted and status != "candidate":
        raise SystemExit(
            "pathway step already has accepted_ts_node; create a new pathway or "
            "supersede the accepted node explicitly before marking the step ambiguous/rejected"
        )
    current_status = clean_string(step.get("status"))
    if current_status == "accepted_ts" and status != "candidate":
        raise SystemExit(
            "pathway step is already accepted_ts; do not silently downgrade it through a failed branch"
        )
    if current_status == "accepted_ts" and status == "candidate":
        return
    step["status"] = status
    step["status_node"] = node_id
    step["updated_at"] = timestamp
    if evidence_refs:
        step["evidence_refs"] = list(evidence_refs)
    pathway["status"] = derive_pathway_status(list_or_empty(pathway.get("steps")))
    model["active_pathway"] = pathway_id
    model["updated_at"] = timestamp
    write_json_object(pathway_model_path(root), model, overwrite_existing=True)


def load_or_default_pathway_model(root: Path, *, system: str, mode: str, timestamp: str) -> dict[str, Any]:
    """Load pathway_model.json or return an empty model."""

    path = pathway_model_path(root)
    if path.exists():
        return read_json_object_required(path)
    return default_pathway_model(system=system, mode=mode, timestamp=timestamp)


def read_pathway_model_required(root: Path) -> dict[str, Any]:
    """Read pathway_model.json and require the current schema."""

    path = pathway_model_path(root)
    if not path.exists():
        raise SystemExit("pathway_model.json does not exist; initialize the workspace with init_workspace first")
    model = read_json_object_required(path)
    if clean_string(model.get("schema")) != PATHWAY_MODEL_SCHEMA:
        raise SystemExit(f"pathway_model.json must declare schema={PATHWAY_MODEL_SCHEMA}")
    return model


def read_pathway_model_optional(root: Path) -> dict[str, Any]:
    """Read pathway_model.json if present."""

    return read_json_object_optional(pathway_model_path(root))


def find_pathway(model: dict[str, Any], pathway_id: str) -> dict[str, Any]:
    """Return a pathway object by id or exit."""

    for item in list_or_empty(model.get("pathways")):
        if isinstance(item, dict) and clean_string(item.get("pathway_id")) == pathway_id:
            return item
    raise SystemExit(f"pathway not found: {pathway_id}")


def find_step(pathway: dict[str, Any], step_id: str) -> dict[str, Any]:
    """Return one pathway step by id or exit."""

    for item in list_or_empty(pathway.get("steps")):
        if isinstance(item, dict) and clean_string(item.get("step_id")) == step_id:
            return item
    raise SystemExit(f"pathway step not found: {step_id}")


def validate_pathway_step_reference(root: Path, pathway_id: str, step_id: str) -> None:
    """Require that a pathway step reference exists."""

    model = read_pathway_model_required(root)
    pathway = find_pathway(model, clean_string(pathway_id))
    find_step(pathway, clean_string(step_id))


def validate_pathway_reference(root: Path, pathway_id: str) -> None:
    """Require that a pathway reference exists."""

    model = read_pathway_model_required(root)
    find_pathway(model, clean_string(pathway_id))


def parse_step_spec(raw: str) -> dict[str, Any]:
    """Parse step_id:from->to into a pathway step object."""

    text = clean_string(raw)
    if ":" not in text or "->" not in text:
        raise SystemExit(f"--step must be step_id:from->to, got {raw!r}")
    step_id, boundary = text.split(":", 1)
    from_state, to_state = boundary.split("->", 1)
    step_id = safe_identifier_token(step_id)
    from_state = clean_string(from_state)
    to_state = clean_string(to_state)
    if not step_id or not from_state or not to_state:
        raise SystemExit(f"--step must be step_id:from->to, got {raw!r}")
    return {
        "step_id": step_id,
        "label": f"{from_state} -> {to_state}",
        "from": from_state,
        "to": to_state,
        "status": "missing",
        "accepted_ts_node": None,
        "evidence_refs": [],
    }


def validate_unique_step_ids(steps: list[dict[str, Any]]) -> None:
    """Reject duplicate step ids in one pathway."""

    seen: set[str] = set()
    for step in steps:
        step_id = clean_string(step.get("step_id"))
        if step_id in seen:
            raise SystemExit(f"duplicate pathway step id: {step_id}")
        seen.add(step_id)


def derive_pathway_status(steps: list[dict[str, Any]]) -> str:
    """Derive a pathway status from step statuses."""

    if not steps:
        return "hypothesis"
    statuses = [clean_string(step.get("status")) or "missing" for step in steps]
    if all(status == "accepted_ts" for status in statuses):
        return "complete"
    if all(status == "rejected" for status in statuses):
        return "rejected"
    if any(status in {"rejected", "ambiguous"} for status in statuses):
        return "ambiguous"
    if any(status in {"accepted_ts", "candidate"} for status in statuses):
        return "partial"
    return "hypothesis"


def summarize_pathway_model(model: dict[str, Any]) -> dict[str, Any]:
    """Return compact planner-facing pathway state."""

    if not model:
        return {"present": False, "mode": "single_step", "active_pathway": None, "pathways": []}
    pathways = [item for item in list_or_empty(model.get("pathways")) if isinstance(item, dict)]
    active_id = clean_string(model.get("active_pathway"))
    active = None
    if active_id:
        active = next((item for item in pathways if clean_string(item.get("pathway_id")) == active_id), None)
    if active is None and pathways:
        active = pathways[-1]
        active_id = clean_string(active.get("pathway_id"))
    return {
        "present": True,
        "schema": clean_string(model.get("schema")),
        "mode": clean_string(model.get("mode")) or "unknown",
        "active_pathway": summarize_pathway(active) if active else None,
        "pathways": [summarize_pathway(item) for item in pathways],
        "next_incomplete_step": next_incomplete_step(active) if active else None,
    }


def summarize_pathway(pathway: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a compact pathway summary."""

    if not pathway:
        return None
    steps = [item for item in list_or_empty(pathway.get("steps")) if isinstance(item, dict)]
    return {
        "pathway_id": clean_string(pathway.get("pathway_id")),
        "label": clean_string(pathway.get("label")),
        "status": clean_string(pathway.get("status")) or derive_pathway_status(steps),
        "accepted_pathway_audit_node": clean_string(pathway.get("accepted_pathway_audit_node")),
        "steps": [
            {
                "step_id": clean_string(step.get("step_id")),
                "label": clean_string(step.get("label")),
                "from": clean_string(step.get("from")),
                "to": clean_string(step.get("to")),
                "status": clean_string(step.get("status")) or "missing",
                "accepted_ts_node": clean_string(step.get("accepted_ts_node")),
                "status_node": clean_string(step.get("status_node")),
            }
            for step in steps
        ],
    }


def next_incomplete_step(pathway: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the first pathway step that does not yet have accepted TS evidence."""

    if not pathway:
        return None
    for step in list_or_empty(pathway.get("steps")):
        if not isinstance(step, dict):
            continue
        if clean_string(step.get("status")) != "accepted_ts" or not clean_string(step.get("accepted_ts_node")):
            return {
                "pathway_id": clean_string(pathway.get("pathway_id")),
                "step_id": clean_string(step.get("step_id")),
                "label": clean_string(step.get("label")),
                "from": clean_string(step.get("from")),
                "to": clean_string(step.get("to")),
                "status": clean_string(step.get("status")) or "missing",
            }
    return None


def evidence_refs_for_node(root: Path, node_id: str) -> list[str]:
    """Return evidence ids attached to a node."""

    registry = read_json_object_optional(root / "evidence_registry.json")
    refs: list[str] = []
    for record in list_or_empty(registry.get("records")):
        if not isinstance(record, dict):
            continue
        if clean_string(record.get("node_id")) != node_id:
            continue
        evidence_id = clean_string(record.get("evidence_id"))
        if evidence_id and evidence_id not in refs:
            refs.append(evidence_id)
    return refs


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()
