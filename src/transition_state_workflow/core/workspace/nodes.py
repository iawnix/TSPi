"""Generic workspace node-record helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import WORKSPACE_NODE_SCHEMA, derive_claim_level

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
    operation = str(extra.pop("operation", decision or stage))
    failure_type = extra.pop("failure_type", None)
    claim_status = str(extra.pop("claim_status", "not_evaluated"))
    outcome = str(extra.pop("outcome", "none"))
    outcome_code = extra.pop("outcome_code", None)
    failure_type = failure_type or outcome_code
    lifecycle_state = str(extra.pop("lifecycle_state", "prepared"))
    run_state = str(extra.pop("run_state", "not_started"))

    if status == "pending":
        lifecycle_state = "active"
        run_state = "pending"
    elif status == "running":
        lifecycle_state = "active"
        run_state = "running"
    elif status == "succeeded":
        lifecycle_state = "closed"
        run_state = "completed"
        if stage in {"neb", "gaussian_external_neb"}:
            claim_status = "candidate_found"
            outcome = "candidate_generated"
    elif status == "ambiguous":
        lifecycle_state = "closed"
        run_state = "completed"
        if failure_type in {"neb_endpoint_candidate", "neb_no_barrier"}:
            claim_status = "rejected"
            outcome = "chemical_failure"
            outcome_code = outcome_code or failure_type
        elif failure_type:
            claim_status = "not_evaluated"
            outcome = "numerical_failure"
            outcome_code = outcome_code or failure_type
        else:
            claim_status = "ambiguous"
            outcome = "parser_refused"
            outcome_code = outcome_code or "ambiguous_candidate_generation"
    elif status == "failed":
        lifecycle_state = "closed"
        run_state = "error"
        claim_status = "not_evaluated"
        outcome = "numerical_failure"
        outcome_code = outcome_code or failure_type or "execution_failed"
    elif status == "accepted":
        lifecycle_state = "closed"
        run_state = "completed"
        claim_status = "accepted_ts"
        outcome = "accepted"
    elif status == "closed":
        lifecycle_state = "closed"

    claim_level = derive_claim_level(claim_status)
    record = {
        "schema": WORKSPACE_NODE_SCHEMA,
        "node_id": node_id,
        "parent_id": parent_id,
        "stage": stage,
        "operation": operation,
        "lifecycle_state": lifecycle_state,
        "run_state": run_state,
        "claim_status": claim_status,
        "outcome": outcome,
        "outcome_code": outcome_code,
        "claim_level": claim_level,
        "created_at": utc_timestamp(),
        "hypothesis": hypothesis,
        "changed_variables": changed_variables or {},
        "evidence": evidence or {},
        "decision": decision,
        "display": {
            "title": node_id,
            "subtitle": stage,
            "badges": [claim_status],
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
