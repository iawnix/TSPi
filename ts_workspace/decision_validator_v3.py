"""Schema and state-aware validation for strategy-neutral v3 decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .evidence_v3 import EvidenceStateError, evidence_view
from .gates_v3 import GateEvaluationError, evaluate_gate, validate_audit_gate_results
from .identity import read_workspace_identity
from .io import read_json
from .model_v3 import DECISION_SCHEMA, GATE_TYPES
from .operational import operational_snapshot
from .refs_v3 import WorkspaceRefError, validate_owner_file_ref
from .revision_v3 import report_id_for_revision, workspace_revision
from .schema_validation import SchemaValidationError, validate_contract
from .state_v3 import CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE, RESEARCH_STATE_FILE


class ContractError(ValueError):
    """Raised when a v3 decision cannot be safely applied."""


def validate_decision(decision: Any) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ContractError("decision must be an object")
    try:
        validate_contract("decision_v3.schema.json", decision)
    except SchemaValidationError as exc:
        raise ContractError(str(exc)) from exc
    if decision.get("schema_version") != DECISION_SCHEMA:
        raise ContractError(f"unsupported decision schema: {decision.get('schema_version')}")

    payload = decision["payload"]
    if decision["action"] == "update_workspace":
        for claim in _items(payload.get("append_claim")):
            unknown = sorted(set(claim.get("required_gates", [])) - GATE_TYPES)
            if unknown:
                raise ContractError("claim required_gates contains unsupported gates: " + ", ".join(unknown))
    return decision


def validate_decision_for_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    value = validate_decision(decision)
    root_path = Path(root).resolve()
    action = value["action"]
    if action == "init_workspace":
        return value
    _require_v3_workspace(root_path)
    _validate_report_binding(root_path, value)
    _require_review_dispositions(root_path)

    research = read_json(root_path / RESEARCH_STATE_FILE)
    claims = read_json(root_path / CLAIMS_FILE)
    evidence = read_json(root_path / EVIDENCE_FILE)
    gates = read_json(root_path / GATE_RESULTS_FILE)
    nodes = _node_map(root_path, research)
    claim_map = _id_map(claims.get("claims", []), "claim_id")
    evidence_rows = list(evidence.get("evidence", []))
    evidence_events = list(evidence.get("events", []))
    gate_rows = list(gates.get("gate_results", []))

    if action == "start_node":
        _validate_start(value["payload"], nodes, claim_map)
    elif action == "update_workspace":
        _validate_update(
            root_path,
            value["payload"],
            nodes,
            claim_map,
            evidence_rows,
            evidence_events,
            gate_rows,
        )
    elif action == "end_node":
        _validate_end(value["payload"], nodes, claim_map, evidence_rows, evidence_events, gate_rows)
    else:
        raise ContractError(f"unsupported workspace mutation action: {action}")
    return value


def _require_review_dispositions(root: Path) -> None:
    pending = operational_snapshot(root)["pending_review_dispositions"]
    if not pending:
        return
    task_ids = ", ".join(str(item.get("task_id") or "unknown") for item in pending)
    raise ContractError(
        "completed advisory Review requires a Root response; "
        f"call ts_review_disposition first for: {task_ids}"
    )


def _validate_start(
    payload: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
) -> None:
    node_id = payload.get("node_id")
    if node_id is not None and node_id in nodes:
        raise ContractError(f"node already exists: {node_id}")
    parent = payload.get("parent_node")
    if parent is not None and parent not in nodes:
        raise ContractError(f"parent_node does not exist: {parent}")
    _require_known(payload.get("claim_refs", []), set(claims), "claim_refs")


def _validate_update(
    root: Path,
    payload: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    evidence_events: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
) -> None:
    future_claims = dict(claims)
    for claim in _items(payload.get("append_claim")):
        claim_id = str(claim["claim_id"])
        if claim_id in future_claims:
            raise ContractError(f"duplicate claim_id: {claim_id}")
        _require_open_node(nodes, str(claim["node_id"]), "append_claim")
        future_claims[claim_id] = claim
    for claim in _items(payload.get("append_claim")):
        parent = claim.get("parent_claim_id")
        if parent is not None and parent not in future_claims:
            raise ContractError(f"parent_claim_id does not exist: {parent}")
    _require_acyclic_claims(future_claims)

    future_evidence = list(evidence_rows)
    evidence_ids = set(_id_map(future_evidence, "evidence_id"))
    for record in _items(payload.get("append_evidence")):
        evidence_id = str(record["evidence_id"])
        if evidence_id in evidence_ids:
            raise ContractError(f"duplicate evidence_id: {evidence_id}")
        node_id = str(record["node_id"])
        _require_open_node(nodes, node_id, "append_evidence")
        for ref in record.get("artifact_refs", []):
            _require_owner_ref(root, ref, node_id, "evidence artifact")
        future_evidence.append(record)
        evidence_ids.add(evidence_id)

    future_events = [*evidence_events, *_items(payload.get("append_evidence_event"))]
    try:
        view = evidence_view(future_evidence, future_events)
    except EvidenceStateError as exc:
        raise ContractError(str(exc)) from exc
    active_evidence = {
        str(item["evidence_id"]): item
        for item in view.active_records
        if isinstance(item.get("evidence_id"), str)
    }

    future_gates = list(gate_rows)
    gate_ids = set(_id_map(future_gates, "gate_result_id"))
    for request in _items(payload.get("evaluate_gate")):
        gate_id = str(request["gate_result_id"])
        if gate_id in gate_ids:
            raise ContractError(f"duplicate gate_result_id: {gate_id}")
        node_id = str(request["node_id"])
        _require_open_node(nodes, node_id, "evaluate_gate")
        target = request.get("target_ref")
        if target is not None and target not in future_claims:
            raise ContractError(f"gate target_ref does not identify a claim: {target}")
        inactive = [ref for ref in request["evidence_refs"] if ref not in active_evidence]
        if inactive:
            raise ContractError("gate evidence is unavailable or inactive: " + ", ".join(inactive))
        try:
            result = evaluate_gate(
                gate_result_id=gate_id,
                node_id=node_id,
                gate=str(request["gate"]),
                evidence_records=list(active_evidence.values()),
                evidence_refs=list(request["evidence_refs"]),
                target_ref=target,
            )
        except GateEvaluationError as exc:
            raise ContractError(str(exc)) from exc
        future_gates.append(result)
        gate_ids.add(gate_id)

    for link in _items(payload.get("link_operation")):
        node_id = str(link["node_id"])
        _require_open_node(nodes, node_id, "link_operation")
        _require_owner_ref(root, link["operation_ref"], node_id, "operation")

    focus_refs = payload.get("set_focus_claim_refs")
    if focus_refs is not None:
        _require_known(focus_refs, set(future_claims), "set_focus_claim_refs")


def _validate_end(
    payload: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    evidence_events: list[dict[str, Any]],
    gate_rows: list[dict[str, Any]],
) -> None:
    node_id = str(payload["node_id"])
    node = _require_open_node(nodes, node_id, "end_node")
    result = payload["result"]
    evidence_ids = set(_id_map(evidence_rows, "evidence_id"))
    gates = _id_map(gate_rows, "gate_result_id")
    node_claims = set(node.get("claim_refs", []))
    try:
        active_evidence_ids = {
            str(item["evidence_id"])
            for item in evidence_view(evidence_rows, evidence_events).active_records
        }
    except EvidenceStateError as exc:
        raise ContractError(str(exc)) from exc
    future_status = {claim_id: str(claim.get("status")) for claim_id, claim in claims.items()}
    updated_claims: set[str] = set()

    for update in result.get("claim_updates", []):
        claim_ref = str(update["claim_ref"])
        if claim_ref not in claims:
            raise ContractError(f"claim update references unknown claim: {claim_ref}")
        if claim_ref not in node_claims:
            raise ContractError(f"claim update is outside node claim_refs: {claim_ref}")
        if claim_ref in updated_claims:
            raise ContractError(f"claim appears more than once in claim_updates: {claim_ref}")
        updated_claims.add(claim_ref)
        _require_known(update.get("evidence_refs", []), evidence_ids, "claim update evidence_refs")
        _require_known(update.get("gate_result_refs", []), set(gates), "claim update gate_result_refs")
        inactive = sorted(ref for ref in update.get("evidence_refs", []) if ref not in active_evidence_ids)
        if inactive:
            raise ContractError("claim update evidence is inactive: " + ", ".join(inactive))
        for gate_ref in update.get("gate_result_refs", []):
            target = gates[gate_ref].get("target_ref")
            if target not in {None, claim_ref}:
                raise ContractError(f"gate result {gate_ref} targets {target}, not {claim_ref}")
            inactive_gate_evidence = sorted(
                ref for ref in gates[gate_ref].get("evidence_refs", []) if ref not in active_evidence_ids
            )
            if inactive_gate_evidence:
                raise ContractError(
                    f"gate result {gate_ref} relies on inactive evidence: {', '.join(inactive_gate_evidence)}"
                )
        if update["verdict"] == "supported":
            required = set(claims[claim_ref].get("required_gates", []))
            selected_gate_refs = set(claims[claim_ref].get("gate_result_refs", [])) | set(
                update.get("gate_result_refs", [])
            )
            passed = {
                str(gates[ref].get("gate"))
                for ref in selected_gate_refs
                if gates[ref].get("verdict") == "pass"
            }
            missing = sorted(required - passed)
            if missing:
                raise ContractError(
                    f"supported claim {claim_ref} is missing passed required gates: {', '.join(missing)}"
                )
        future_status[claim_ref] = str(update["verdict"])

    audit = result.get("audit")
    if not isinstance(audit, dict):
        return
    target = str(audit["target_ref"])
    if target not in claims:
        raise ContractError(f"audit target_ref does not identify a claim: {target}")
    if target not in node_claims:
        raise ContractError(f"audit target_ref is outside node claim_refs: {target}")
    _require_known(audit["gate_result_refs"], set(gates), "audit gate_result_refs")
    if audit["verdict"] == "accepted":
        if audit["study_complete"] is not True:
            raise ContractError("accepted audit requires study_complete=true")
        if future_status.get(target) != "supported":
            raise ContractError("accepted audit requires the target claim to be supported")
        inactive = sorted(
            ref
            for gate_ref in audit["gate_result_refs"]
            for ref in gates[gate_ref].get("evidence_refs", [])
            if ref not in active_evidence_ids
        )
        if inactive:
            raise ContractError("accepted audit relies on inactive evidence: " + ", ".join(inactive))
        try:
            validate_audit_gate_results(
                str(audit["policy"]),
                gate_rows,
                list(audit["gate_result_refs"]),
                target_ref=target,
            )
        except GateEvaluationError as exc:
            raise ContractError(str(exc)) from exc


def _validate_report_binding(root: Path, decision: dict[str, Any]) -> None:
    report_ref = decision.get("report_ref")
    if not isinstance(report_ref, dict):
        raise ContractError("workspace mutation requires report_ref")
    if Path(str(report_ref.get("workspace_root"))).resolve() != root:
        raise ContractError("report_ref.workspace_root does not match the target workspace")
    revision = workspace_revision(root)
    if decision.get("base_revision") != revision:
        raise ContractError("base_revision does not match the current workspace revision")
    if report_ref.get("report_id") != report_id_for_revision(revision):
        raise ContractError("report_ref.report_id does not match the current workspace revision")


def _require_v3_workspace(root: Path) -> None:
    for name in (RESEARCH_STATE_FILE, CLAIMS_FILE, EVIDENCE_FILE, GATE_RESULTS_FILE):
        if not (root / name).is_file():
            raise ContractError(f"workspace is not initialized for v3: missing {name}")
    research = read_json(root / RESEARCH_STATE_FILE)
    if research.get("schema_version") != "ts-research-state/3":
        raise ContractError("workspace is not a ts-research-state/3 workspace")
    read_workspace_identity(root)


def _node_map(root: Path, research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for row in research.get("nodes", []):
        if not isinstance(row, dict) or not isinstance(row.get("node_id"), str):
            continue
        node_id = row["node_id"]
        node_path = root / "nodes" / node_id / "node.json"
        if not node_path.is_file():
            raise ContractError(f"node record does not exist: {node_id}")
        nodes[node_id] = read_json(node_path)
    return nodes


def _require_open_node(
    nodes: dict[str, dict[str, Any]],
    node_id: str,
    operation: str,
) -> dict[str, Any]:
    node = nodes.get(node_id)
    if node is None:
        raise ContractError(f"{operation} references unknown node: {node_id}")
    if node.get("state") != "open":
        raise ContractError(f"{operation} requires an open node: {node_id}")
    return node


def _require_owner_ref(root: Path, value: Any, node_id: str, label: str) -> None:
    try:
        validate_owner_file_ref(root, value, owner_node=node_id)
    except WorkspaceRefError as exc:
        raise ContractError(f"invalid {label} ref {value}: {exc}") from exc


def _require_known(values: Iterable[Any], known: set[str], label: str) -> None:
    missing = sorted(str(value) for value in values if value not in known)
    if missing:
        raise ContractError(f"{label} contains unknown refs: {', '.join(missing)}")


def _id_map(rows: Iterable[Any], key: str) -> dict[str, dict[str, Any]]:
    return {
        str(row[key]): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get(key), str)
    }


def _items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _require_acyclic_claims(claims: dict[str, dict[str, Any]]) -> None:
    for start in claims:
        current: str | None = start
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise ContractError(f"claim parent cycle detected at {current}")
            seen.add(current)
            claim = claims.get(current)
            if claim is None:
                break
            parent = claim.get("parent_claim_id")
            current = str(parent) if parent is not None else None
