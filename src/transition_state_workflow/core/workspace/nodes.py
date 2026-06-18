"""Generic workspace node-record helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import WORKSPACE_NODE_SCHEMA, normalize_public_phase

from .naming import utc_timestamp, workspace_slug


VALID_NODE_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "ambiguous",
    "accepted",
    "closed",
}


def node_record(
    *,
    node_id: str,
    parent_id: str | None,
    node_type: str,
    hypothesis: str,
    changed_variables: dict[str, Any] | None,
    status: str,
    evidence: dict[str, Any] | None,
    decision: str,
    backtrack_to: str | None = None,
    children: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a v2 workspace node record from a compact legacy status."""

    if status not in VALID_NODE_STATUSES:
        raise ValueError(f"invalid node status '{status}' for {node_id}")
    stage = str(extra.pop("stage", node_type))
    phase = normalize_public_phase(stage, fallback_stage=stage)
    operation = str(extra.pop("operation", decision or stage))
    failure_type = extra.pop("failure_type", None)
    extra.pop("claim_status", None)
    extra.pop("outcome", None)
    outcome_code = extra.pop("outcome_code", None)
    failure_type = failure_type or outcome_code
    extra.pop("lifecycle_state", None)
    extra.pop("run_state", None)
    node_disposition = "Running"

    if status in {"pending", "running"}:
        node_disposition = "Running"
    elif status == "succeeded":
        node_disposition = "Success"
    elif status == "ambiguous":
        node_disposition = "Error" if failure_type else "Success"
    elif status == "failed":
        node_disposition = "Error"
        outcome_code = outcome_code or failure_type or "execution_failed"
    elif status == "accepted":
        node_disposition = "Success"
        phase = "accepted_audit"
    elif status == "closed":
        node_disposition = "Success"

    closure_explanation = None
    if node_disposition in {"Stopped", "Error", "Success"}:
        closure_explanation = {
            "program": {
                "summary": hypothesis,
                "facts": [],
            },
            "mechanism": {
                "summary": "Mechanism implications are recorded in node evidence and reflection.",
                "facts": [],
            },
            "implication": "Inspect report_workspace before opening the next node.",
            "open_questions": [],
        }
    record = {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": node_id,
        "parent_id": parent_id,
        "phase": phase,
        "operation": operation,
        "node_disposition": node_disposition,
        "closure_explanation": closure_explanation,
        "created_at": utc_timestamp(),
        "hypothesis": hypothesis,
        "evidence": evidence or {},
        "decision": decision,
        "display": {
            "title": node_id,
            "subtitle": phase,
            "badges": [node_disposition, phase],
            "metrics": {},
            "primary_file": "",
            "summary": hypothesis,
        },
    }
    if backtrack_to is not None:
        record["backtrack_to"] = backtrack_to
    if children is not None:
        record["children"] = children
    record.update(extra)
    return record


def next_node_id(root: Path, stage_slug: str, *, start: int = 20) -> str:
    """Return the next nNNN stage id under a workspace nodes directory."""

    nodes_dir = root / "nodes"
    used: list[int] = []
    if nodes_dir.exists():
        for path in nodes_dir.iterdir():
            match = re.match(r"n(\d{3})_", path.name)
            if match:
                used.append(int(match.group(1)))
    number = start if not used else max(used) + 10
    return f"n{number:03d}_{workspace_slug(stage_slug)}"


__all__ = ["VALID_NODE_STATUSES", "node_record", "next_node_id"]
