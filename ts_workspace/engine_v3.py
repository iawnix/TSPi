"""Strategy-neutral v3 workspace mutation engine."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .decision_validator_v3 import ContractError, validate_decision, validate_decision_for_workspace
from .evidence_v3 import evidence_view
from .gates_v3 import evaluate_gate, validate_audit_gate_results
from .identity import WorkspaceIdentityError, ensure_workspace_identity
from .io import now_iso, read_json, write_json
from .model_v3 import NODE_SCHEMA
from .state_v3 import (
    CLAIMS_FILE,
    EVIDENCE_FILE,
    GATE_RESULTS_FILE,
    OPTIONAL_DIRS,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    RESEARCH_STATE_FILE,
    initial_claim_registry,
    initial_evidence_registry,
    initial_gate_registry,
    initial_research_state,
)
from .transactions import (
    TRANSACTION_DIR,
    WORKSPACE_LOCK,
    commit_transaction,
    committed_decision_result,
    recover_incomplete_transactions,
    workspace_lock,
)
from .validator_v3 import validate_workspace as validate_workspace_dict


DRY_RUN_EXCLUDED_DIRS = frozenset({
    ".git",
    ".pi",
    ".pytest_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "node_modules",
    TRANSACTION_DIR,
    WORKSPACE_LOCK,
})


def init_workspace(
    root: str | Path,
    decision: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    if decision is not None:
        validate_decision(decision)
        _require_action(decision, "init_workspace")
    elif force:
        raise ContractError("force reinitialize requires an init_workspace decision")
    if root_path.is_symlink():
        raise ContractError("workspace root cannot be a symbolic link")
    existing = [name for name in REQUIRED_FILES if (root_path / name).exists()]
    if existing and not force:
        raise ContractError("workspace already initialized: " + ", ".join(sorted(existing)))
    if force and root_path.exists():
        _ensure_workspace_identity(root_path)
        _clear_workspace_state(root_path)

    root_path.mkdir(parents=True, exist_ok=True)
    for dirname in REQUIRED_DIRS:
        (root_path / dirname).mkdir(parents=True, exist_ok=True)
    write_json(root_path / RESEARCH_STATE_FILE, initial_research_state())
    write_json(root_path / CLAIMS_FILE, initial_claim_registry())
    write_json(root_path / EVIDENCE_FILE, initial_evidence_registry())
    write_json(root_path / GATE_RESULTS_FILE, initial_gate_registry())
    (root_path / "decision_log.jsonl").touch(mode=0o600)
    (root_path / "transaction_log.jsonl").touch(mode=0o600)
    identity = _ensure_workspace_identity(root_path)
    if decision is not None:
        commit_transaction(root_path, decision, {}, {"mutation_applied": True})
    validation = validate_workspace_dict(root_path)
    return {
        "root": str(root_path),
        "workspace_id": identity["workspace_id"],
        "created": True,
        "valid": validation["valid"],
    }


def _ensure_workspace_identity(root: Path) -> dict[str, str]:
    try:
        return ensure_workspace_identity(root)
    except WorkspaceIdentityError as exc:
        raise ContractError(str(exc)) from exc


def start_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_mutation(root, decision, "start_node", _start_node_once)


def update_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_mutation(root, decision, "update_workspace", _update_workspace_once)


def end_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_mutation(root, decision, "end_node", _end_node_once)


def _start_node_once(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    payload = decision["payload"]
    research_path = root / RESEARCH_STATE_FILE
    research = read_json(research_path)
    node_id = payload.get("node_id") or _next_node_id(research)
    node_dir = root / "nodes" / node_id
    if (node_dir / "node.json").exists():
        raise ContractError(f"node already exists: {node_id}")
    timestamp = now_iso()
    node = {
        "schema_version": NODE_SCHEMA,
        "node_id": node_id,
        "parent_node": payload.get("parent_node"),
        "objective": payload["objective"],
        "state": "open",
        "tags": list(payload.get("tags", [])),
        "claim_refs": list(payload.get("claim_refs", [])),
        "operation_refs": [],
        "evidence_refs": [],
        "gate_result_refs": [],
        "created_by_decision": decision["decision_id"],
        "opened_at": timestamp,
        "artifacts": {
            "inputs": f"nodes/{node_id}/inputs",
            "outputs": f"nodes/{node_id}/outputs",
            "attempts": f"nodes/{node_id}/attempts",
            "scratch": f"nodes/{node_id}/scratch",
        },
        "result": None,
    }
    summary = {
        "node_id": node_id,
        "parent_node": node["parent_node"],
        "objective": node["objective"],
        "state": node["state"],
        "tags": node["tags"],
    }
    research["nodes"].append(summary)
    research["open_nodes"].append(node_id)
    if node["parent_node"] is not None:
        research["edges"].append({"parent_node": node["parent_node"], "child_node": node_id})
    research["branch_events"].append(
        {
            "node_id": node_id,
            "parent_node": node["parent_node"],
            "decision_id": decision["decision_id"],
            "created_at": timestamp,
        }
    )
    directories = [node_dir]
    changes = {
        node_dir / "node.json": node,
        node_dir / "decision.md": decision["rationale"].strip() + "\n",
        research_path: research,
    }
    result = {"node_id": node_id, "state": "open"}
    commit_transaction(root, decision, changes, result, directories=directories)
    return result


def _update_workspace_once(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    payload = decision["payload"]
    research_path = root / RESEARCH_STATE_FILE
    claims_path = root / CLAIMS_FILE
    evidence_path = root / EVIDENCE_FILE
    gates_path = root / GATE_RESULTS_FILE
    research = read_json(research_path)
    claims = read_json(claims_path)
    evidence = read_json(evidence_path)
    gates = read_json(gates_path)
    nodes = _node_documents(root, research)
    timestamp = now_iso()
    counts = {"claims": 0, "evidence": 0, "evidence_events": 0, "gate_results": 0, "operations": 0, "provenance": 0}

    for item in _items(payload.get("append_claim")):
        record = {
            "claim_id": item["claim_id"],
            "created_in_node": item["node_id"],
            **({"parent_claim_id": item["parent_claim_id"]} if item.get("parent_claim_id") is not None else {}),
            "kind": item["kind"],
            "statement": item["statement"],
            "status": "proposed",
            "required_gates": list(item.get("required_gates", [])),
            "evidence_refs": [],
            "gate_result_refs": [],
            "details": dict(item.get("details", {})),
            "created_by_decision": decision["decision_id"],
            "created_at": timestamp,
            "history": [],
        }
        claims["claims"].append(record)
        _append_unique(nodes[item["node_id"]]["claim_refs"], item["claim_id"])
        counts["claims"] += 1

    for item in _items(payload.get("append_evidence")):
        record = dict(item)
        record.setdefault("created_at", timestamp)
        evidence["evidence"].append(record)
        _append_unique(nodes[item["node_id"]]["evidence_refs"], item["evidence_id"])
        counts["evidence"] += 1

    for item in _items(payload.get("append_evidence_event")):
        record = dict(item)
        record["created_at"] = timestamp
        evidence["events"].append(record)
        counts["evidence_events"] += 1

    active_view = evidence_view(evidence["evidence"], evidence["events"])
    active_records = active_view.active_records
    for request in _items(payload.get("evaluate_gate")):
        result = evaluate_gate(
            gate_result_id=request["gate_result_id"],
            node_id=request["node_id"],
            gate=request["gate"],
            evidence_records=active_records,
            evidence_refs=list(request["evidence_refs"]),
            target_ref=request.get("target_ref"),
        )
        gates["gate_results"].append(result)
        _append_unique(nodes[request["node_id"]]["gate_result_refs"], request["gate_result_id"])
        counts["gate_results"] += 1

    for link in _items(payload.get("link_operation")):
        _append_unique(nodes[link["node_id"]]["operation_refs"], link["operation_ref"])
        counts["operations"] += 1

    if "set_focus_claim_refs" in payload:
        claims["focus_claim_refs"] = list(payload["set_focus_claim_refs"])
    provenance = _items(payload.get("append_provenance"))
    research["provenance"].extend(provenance)
    counts["provenance"] = len(provenance)

    changes: dict[Path, Any] = {
        research_path: research,
        claims_path: claims,
        evidence_path: evidence,
        gates_path: gates,
    }
    for node_id, node in nodes.items():
        changes[root / "nodes" / node_id / "node.json"] = node
    result = {"appended": counts, "focus_claim_refs": list(claims["focus_claim_refs"])}
    commit_transaction(root, decision, changes, result)
    return result


def _end_node_once(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    payload = decision["payload"]
    node_id = payload["node_id"]
    result_payload = dict(payload["result"])
    timestamp = now_iso()
    research_path = root / RESEARCH_STATE_FILE
    claims_path = root / CLAIMS_FILE
    gates_path = root / GATE_RESULTS_FILE
    node_path = root / "nodes" / node_id / "node.json"
    research = read_json(research_path)
    claims = read_json(claims_path)
    gates = read_json(gates_path)
    node = read_json(node_path)
    claim_map = {item["claim_id"]: item for item in claims["claims"]}

    for update in result_payload.get("claim_updates", []):
        claim = claim_map[update["claim_ref"]]
        claim["status"] = update["verdict"]
        for ref in update["evidence_refs"]:
            _append_unique(claim["evidence_refs"], ref)
            _append_unique(node["evidence_refs"], ref)
        for ref in update["gate_result_refs"]:
            _append_unique(claim["gate_result_refs"], ref)
            _append_unique(node["gate_result_refs"], ref)
        claim["history"].append(
            {
                "node_id": node_id,
                "verdict": update["verdict"],
                "summary": update["summary"],
                "evidence_refs": list(update["evidence_refs"]),
                "gate_result_refs": list(update["gate_result_refs"]),
                "decision_id": decision["decision_id"],
                "created_at": timestamp,
            }
        )

    changes: dict[Path, Any] = {claims_path: claims}
    audit = result_payload.get("audit")
    accepted_ref = None
    if isinstance(audit, dict):
        for ref in audit["gate_result_refs"]:
            _append_unique(node["gate_result_refs"], ref)
        if audit["verdict"] == "accepted":
            validate_audit_gate_results(
                audit["policy"],
                gates["gate_results"],
                audit["gate_result_refs"],
                target_ref=audit["target_ref"],
            )
            acceptance_id = f"acc_{decision['decision_id']}"
            accepted_ref = f"accepted/{acceptance_id}.json"
            changes[root / accepted_ref] = {
                "schema_version": "ts-accepted-claim/1",
                "acceptance_id": acceptance_id,
                "node_id": node_id,
                "policy": audit["policy"],
                "target_ref": audit["target_ref"],
                "gate_result_refs": list(audit["gate_result_refs"]),
                "summary": audit["summary"],
                "decision_id": decision["decision_id"],
                "created_at": timestamp,
            }
            _append_unique(research["accepted_refs"], accepted_ref)

    state = "stopped" if result_payload["outcome"] == "stopped" else "closed"
    node["state"] = state
    node["result"] = result_payload
    node["closed_at"] = timestamp
    node["ended_by_decision"] = decision["decision_id"]
    for row in research["nodes"]:
        if row.get("node_id") == node_id:
            row["state"] = state
            row["outcome"] = result_payload["outcome"]
            row["closed_at"] = timestamp
            break
    research["open_nodes"] = [value for value in research["open_nodes"] if value != node_id]
    changes.update({research_path: research, node_path: node})
    result = {"node_id": node_id, "state": state, "outcome": result_payload["outcome"], "accepted_ref": accepted_ref}
    commit_transaction(root, decision, changes, result)
    return result


def validate_decision_dry_run(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root).resolve()
    validate_decision_for_workspace(root_path, decision)
    with tempfile.TemporaryDirectory(prefix="ts-workspace-v3-dry-run-") as temporary:
        target = Path(temporary) / "workspace"
        shutil.copytree(root_path, target, ignore=_ignore_dry_run_entries)
        result = _mutation_for_action(decision["action"])(target, decision)
        validation = validate_workspace_dict(target)
        if not validation["valid"]:
            messages = "; ".join(item["message"] for item in validation["findings"] if item["severity"] == "error")
            raise ContractError(f"decision dry run produced an invalid workspace: {messages}")
        return {"action": decision["action"], "result": result, "post_validation": validation}


def validate_workspace(root: str | Path) -> dict[str, Any]:
    return validate_workspace_dict(root)


def report_workspace(root: str | Path) -> dict[str, Any]:
    from .reader_v3 import report_workspace as build

    return build(root)


def report_node(root: str | Path, node_id: str) -> dict[str, Any]:
    from .reader_v3 import report_node as build

    return build(root, node_id)


def report_lineage_context(root: str | Path, from_node: str, anchor_node: str) -> dict[str, Any]:
    from .reader_v3 import report_lineage_context as build

    return build(root, from_node, anchor_node)


def snapshot_report(root: str | Path) -> dict[str, Any]:
    from .reader_v3 import snapshot_report as build

    return build(root)


def build_review_snapshot(
    root: str | Path,
    *,
    target_claim_ref: str,
    node_ids: list[str] | None = None,
) -> dict[str, Any]:
    from .reader_v3 import build_review_snapshot as build

    return build(root, target_claim_ref=target_claim_ref, node_ids=node_ids)


def _apply_mutation(
    root: str | Path,
    decision: dict[str, Any],
    expected_action: str,
    mutation: Callable[[Path, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    _require_action(decision, expected_action)
    _require_initialized(root_path)
    with workspace_lock(root_path):
        recover_incomplete_transactions(root_path)
        replay = committed_decision_result(root_path, decision)
        if replay is not None:
            return replay
        validate_decision_dry_run(root_path, decision)
        return mutation(root_path, decision)


def _mutation_for_action(action: str) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
    mapping = {
        "start_node": _start_node_once,
        "update_workspace": _update_workspace_once,
        "end_node": _end_node_once,
    }
    try:
        return mapping[action]
    except KeyError as exc:
        raise ContractError(f"unsupported mutation action: {action}") from exc


def _require_action(decision: dict[str, Any], expected: str) -> None:
    if decision.get("action") != expected:
        raise ContractError(f"decision action {decision.get('action')!r} does not match command {expected!r}")


def _require_initialized(root: Path) -> None:
    if not (root / RESEARCH_STATE_FILE).is_file():
        raise ContractError(f"workspace is not initialized: {root}")


def _node_documents(root: Path, research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["node_id"]: read_json(root / "nodes" / row["node_id"] / "node.json")
        for row in research["nodes"]
    }


def _next_node_id(research: dict[str, Any]) -> str:
    used = {str(item.get("node_id")) for item in research.get("nodes", []) if isinstance(item, dict)}
    index = 0
    while f"n{index:03d}" in used:
        index += 1
    return f"n{index:03d}"


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _ignore_dry_run_entries(_directory: str, names: list[str]) -> set[str]:
    return set(names) & DRY_RUN_EXCLUDED_DIRS


def _clear_workspace_state(root: Path) -> None:
    for name in REQUIRED_FILES | {"transaction_log.jsonl"}:
        (root / name).unlink(missing_ok=True)
    for name in REQUIRED_DIRS | OPTIONAL_DIRS | {TRANSACTION_DIR}:
        path = root / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
