"""Whole-workspace validation for the strategy-neutral v3 contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence_v3 import EvidenceStateError, evidence_view
from .gates_v3 import GateEvaluationError, evaluate_gate, validate_audit_gate_results
from .identity import IDENTITY_REF, WorkspaceIdentityError, read_workspace_identity
from .io import read_json
from .model_v3 import GATE_TYPES
from .refs_v3 import WorkspaceRefError, validate_owner_file_ref
from .schema_validation import schema_findings
from .state_v3 import (
    CLAIMS_FILE,
    EVIDENCE_FILE,
    GATE_RESULTS_FILE,
    OPTIONAL_DIRS,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    RESEARCH_STATE_FILE,
)


def validate_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    findings: list[dict[str, str]] = []
    for name in sorted(REQUIRED_FILES):
        if not (root_path / name).is_file():
            _finding(findings, "error", "missing_required_file", f"missing required file: {name}", name)
    for name in sorted(REQUIRED_DIRS):
        path = root_path / name
        if path.is_symlink() or not path.is_dir():
            _finding(findings, "error", "missing_required_directory", f"missing required directory: {name}", name)
    for name in sorted(OPTIONAL_DIRS):
        path = root_path / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            _finding(
                findings,
                "error",
                "invalid_optional_directory",
                f"optional workspace path is not a physical directory: {name}",
                name,
            )

    identity_path = root_path / IDENTITY_REF
    if not identity_path.exists() and not identity_path.is_symlink():
        _finding(
            findings,
            "warning",
            "missing_workspace_identity",
            "missing workspace identity (created before remote preparation)",
            IDENTITY_REF,
        )
    else:
        try:
            read_workspace_identity(root_path)
        except WorkspaceIdentityError as exc:
            _finding(findings, "error", "invalid_workspace_identity", str(exc), IDENTITY_REF)
    if any(item["severity"] == "error" for item in findings):
        return _report(root_path, findings)

    document_schemas = {
        RESEARCH_STATE_FILE: "research_state_v3.schema.json",
        CLAIMS_FILE: "claim_registry.schema.json",
        EVIDENCE_FILE: "evidence_registry_v2.schema.json",
        GATE_RESULTS_FILE: "gate_registry.schema.json",
    }
    documents: dict[str, tuple[str, Any]] = {}
    for source, schema in document_schemas.items():
        value = _read_json_for_validation(root_path / source, source, findings)
        if value is not None:
            documents[source] = (schema, value)
    if len(documents) != len(document_schemas):
        return _report(root_path, findings)
    for source, (schema, value) in documents.items():
        findings.extend(schema_findings(schema, value, source))
    research = documents[RESEARCH_STATE_FILE][1]
    claims = documents[CLAIMS_FILE][1]
    evidence_registry = documents[EVIDENCE_FILE][1]
    gate_registry = documents[GATE_RESULTS_FILE][1]
    if not all(isinstance(value, dict) for _, value in documents.values()):
        return _report(root_path, findings)

    node_rows = [item for item in research.get("nodes", []) if isinstance(item, dict)]
    node_ids = _unique_ids(node_rows, "node_id", findings, RESEARCH_STATE_FILE)
    node_details: dict[str, dict[str, Any]] = {}
    for node_id in sorted(node_ids):
        path = root_path / "nodes" / node_id / "node.json"
        if not path.is_file():
            _finding(findings, "error", "missing_node", f"missing node.json for {node_id}", str(path.relative_to(root_path)))
            continue
        node = _read_json_for_validation(path, str(path.relative_to(root_path)), findings)
        if not isinstance(node, dict):
            continue
        node_details[node_id] = node
        findings.extend(schema_findings("node_v3.schema.json", node, str(path.relative_to(root_path))))
        summary = next((item for item in node_rows if item.get("node_id") == node_id), {})
        for key in ("parent_node", "objective", "state", "tags"):
            if summary.get(key) != node.get(key):
                _finding(findings, "error", "node_index_mismatch", f"research_state {key} differs from node.json", f"nodes/{node_id}/node.json")
        if node.get("state") == "open":
            for key in ("outcome", "closed_at"):
                if key in summary:
                    _finding(findings, "error", "node_index_mismatch", f"open node index cannot contain {key}", RESEARCH_STATE_FILE)
        else:
            result = node.get("result") if isinstance(node.get("result"), dict) else {}
            if summary.get("outcome") != result.get("outcome") or summary.get("closed_at") != node.get("closed_at"):
                _finding(findings, "error", "node_index_mismatch", "closed node outcome or closed_at differs from node.json", RESEARCH_STATE_FILE)

    open_nodes = set(str(item) for item in research.get("open_nodes", []))
    actual_open = {node_id for node_id, node in node_details.items() if node.get("state") == "open"}
    if open_nodes != actual_open:
        _finding(findings, "error", "open_nodes_mismatch", "research_state.open_nodes does not match open node files", RESEARCH_STATE_FILE)
    expected_edges = {
        (str(node.get("parent_node")), node_id)
        for node_id, node in node_details.items()
        if node.get("parent_node") is not None
    }
    actual_edges = {
        (str(row.get("parent_node")), str(row.get("child_node")))
        for row in research.get("edges", [])
        if isinstance(row, dict)
    }
    if actual_edges != expected_edges:
        _finding(findings, "error", "edge_index_mismatch", "research_state.edges does not match node parents", RESEARCH_STATE_FILE)
    _check_branch_events(research.get("branch_events", []), node_details, findings)
    _check_parent_cycles(node_details, findings)
    for node_id, node in node_details.items():
        parent = node.get("parent_node")
        if parent is not None and parent not in node_ids:
            _finding(findings, "error", "unknown_parent", f"node {node_id} references unknown parent {parent}", f"nodes/{node_id}/node.json")

    claim_rows = [item for item in claims.get("claims", []) if isinstance(item, dict)]
    claim_ids = _unique_ids(claim_rows, "claim_id", findings, CLAIMS_FILE)
    evidence_rows = [item for item in evidence_registry.get("evidence", []) if isinstance(item, dict)]
    evidence_ids = _unique_ids(evidence_rows, "evidence_id", findings, EVIDENCE_FILE)
    gate_rows = [item for item in gate_registry.get("gate_results", []) if isinstance(item, dict)]
    gate_ids = _unique_ids(gate_rows, "gate_result_id", findings, GATE_RESULTS_FILE)
    try:
        active_view = evidence_view(evidence_rows, evidence_registry.get("events", []))
    except EvidenceStateError as exc:
        _finding(findings, "error", "invalid_evidence_state", str(exc), EVIDENCE_FILE)
        active_view = None
    active_evidence_ids = (
        {str(row.get("evidence_id")) for row in active_view.active_records}
        if active_view is not None
        else set()
    )

    for evidence in evidence_rows:
        _check_ref(evidence.get("node_id"), node_ids, findings, "unknown_evidence_node", EVIDENCE_FILE)
        owner = node_details.get(str(evidence.get("node_id")))
        if owner is not None and evidence.get("evidence_id") not in owner.get("evidence_refs", []):
            _finding(findings, "error", "evidence_owner_index_mismatch", "evidence is missing from owner node evidence_refs", EVIDENCE_FILE)
        for ref in evidence.get("artifact_refs", []):
            error = _workspace_file_ref_error(root_path, ref, owner_node=str(evidence.get("node_id") or ""))
            if error:
                _finding(findings, "error", "invalid_artifact_ref", f"invalid evidence artifact ref {ref}: {error}", EVIDENCE_FILE)
    for result in gate_rows:
        _check_ref(result.get("node_id"), node_ids, findings, "unknown_gate_node", GATE_RESULTS_FILE)
        owner = node_details.get(str(result.get("node_id")))
        if owner is not None and result.get("gate_result_id") not in owner.get("gate_result_refs", []):
            _finding(findings, "error", "gate_owner_index_mismatch", "gate result is missing from evaluator node gate_result_refs", GATE_RESULTS_FILE)
        for ref in result.get("evidence_refs", []):
            _check_ref(ref, evidence_ids, findings, "unknown_gate_evidence", GATE_RESULTS_FILE)
        target = result.get("target_ref")
        if target is not None:
            _check_ref(target, claim_ids, findings, "unknown_gate_target", GATE_RESULTS_FILE)
        try:
            recomputed = evaluate_gate(
                gate_result_id=str(result.get("gate_result_id")),
                node_id=str(result.get("node_id")),
                gate=str(result.get("gate")),
                evidence_records=evidence_rows,
                evidence_refs=list(result.get("evidence_refs", [])),
                target_ref=target,
            )
            for key in ("policy", "verdict", "evaluator", "diagnostics"):
                if result.get(key) != recomputed.get(key):
                    _finding(findings, "error", "gate_result_mismatch", f"stored gate {key} differs from deterministic evaluation", GATE_RESULTS_FILE)
        except GateEvaluationError as exc:
            _finding(findings, "error", "invalid_gate_result", str(exc), GATE_RESULTS_FILE)
    for claim in claim_rows:
        created_in = claim.get("created_in_node")
        _check_ref(created_in, node_ids, findings, "unknown_claim_node", CLAIMS_FILE)
        owner = node_details.get(str(created_in))
        if owner is not None and claim.get("claim_id") not in owner.get("claim_refs", []):
            _finding(findings, "error", "claim_owner_index_mismatch", "claim is missing from creator node claim_refs", CLAIMS_FILE)
        parent = claim.get("parent_claim_id")
        if parent is not None:
            _check_ref(parent, claim_ids, findings, "unknown_parent_claim", CLAIMS_FILE)
        unknown_gates = sorted(set(claim.get("required_gates", [])) - GATE_TYPES)
        if unknown_gates:
            _finding(findings, "error", "unknown_required_gate", "claim requires unsupported gates: " + ", ".join(unknown_gates), CLAIMS_FILE)
        for ref in claim.get("evidence_refs", []):
            _check_ref(ref, evidence_ids, findings, "unknown_claim_evidence", CLAIMS_FILE)
        for ref in claim.get("gate_result_refs", []):
            _check_ref(ref, gate_ids, findings, "unknown_claim_gate", CLAIMS_FILE)
        for history in claim.get("history", []):
            if not isinstance(history, dict):
                continue
            _check_ref(history.get("node_id"), node_ids, findings, "unknown_claim_history_node", CLAIMS_FILE)
            for ref in history.get("evidence_refs", []):
                _check_ref(ref, evidence_ids, findings, "unknown_claim_history_evidence", CLAIMS_FILE)
            for ref in history.get("gate_result_refs", []):
                _check_ref(ref, gate_ids, findings, "unknown_claim_history_gate", CLAIMS_FILE)
        if claim.get("status") == "supported":
            _validate_supported_claim(claim, gate_rows, active_view, findings)
    _check_claim_cycles(claim_rows, findings)
    for ref in claims.get("focus_claim_refs", []):
        _check_ref(ref, claim_ids, findings, "unknown_focus_claim", CLAIMS_FILE)
    for node_id, node in node_details.items():
        for ref in node.get("claim_refs", []):
            _check_ref(ref, claim_ids, findings, "unknown_node_claim", f"nodes/{node_id}/node.json")
        for ref in node.get("evidence_refs", []):
            _check_ref(ref, evidence_ids, findings, "unknown_node_evidence", f"nodes/{node_id}/node.json")
        for ref in node.get("gate_result_refs", []):
            _check_ref(ref, gate_ids, findings, "unknown_node_gate_result", f"nodes/{node_id}/node.json")
        for ref in node.get("operation_refs", []):
            error = _workspace_file_ref_error(root_path, ref, owner_node=node_id)
            if error:
                _finding(findings, "error", "invalid_operation_ref", f"invalid operation ref {ref}: {error}", f"nodes/{node_id}/node.json")
        result = node.get("result")
        audit = result.get("audit") if isinstance(result, dict) and isinstance(result.get("audit"), dict) else None
        if audit and audit.get("verdict") == "accepted":
            try:
                validate_audit_gate_results(
                    str(audit.get("policy")),
                    gate_rows,
                    list(audit.get("gate_result_refs", [])),
                    target_ref=str(audit.get("target_ref")),
                )
            except GateEvaluationError as exc:
                _finding(findings, "error", "invalid_accepted_audit", str(exc), f"nodes/{node_id}/node.json")
    claim_map = {str(row.get("claim_id")): row for row in claim_rows}
    gate_map = {str(row.get("gate_result_id")): row for row in gate_rows}
    accepted_audits: set[tuple[str, str]] = set()
    for ref in research.get("accepted_refs", []):
        audit_key = _validate_accepted_ref(
            root_path,
            ref,
            node_details,
            claim_map,
            gate_map,
            active_evidence_ids,
            findings,
        )
        if audit_key is not None:
            accepted_audits.add(audit_key)
    for node_id, node in node_details.items():
        result = node.get("result") if isinstance(node.get("result"), dict) else {}
        audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
        if audit.get("verdict") == "accepted" and (node_id, str(node.get("ended_by_decision"))) not in accepted_audits:
            _finding(
                findings,
                "error",
                "accepted_audit_missing_artifact",
                "accepted node audit has no matching accepted artifact",
                f"nodes/{node_id}/node.json",
            )
    return _report(root_path, findings)


def _validate_supported_claim(
    claim: dict[str, Any],
    gate_rows: list[dict[str, Any]],
    active_view: Any,
    findings: list[dict[str, str]],
) -> None:
    by_id = {row.get("gate_result_id"): row for row in gate_rows}
    selected = [by_id.get(ref) for ref in claim.get("gate_result_refs", [])]
    passed = {row.get("gate") for row in selected if isinstance(row, dict) and row.get("verdict") == "pass"}
    missing = sorted(set(claim.get("required_gates", [])) - passed)
    if missing:
        _finding(findings, "error", "supported_claim_missing_gates", "supported claim lacks passed gates: " + ", ".join(missing), CLAIMS_FILE)
    if active_view is None:
        return
    active_ids = {row.get("evidence_id") for row in active_view.active_records}
    used_refs = set(claim.get("evidence_refs", []))
    used_refs.update(
        ref
        for row in selected
        if isinstance(row, dict)
        for ref in row.get("evidence_refs", [])
    )
    inactive = sorted(ref for ref in used_refs if ref not in active_ids)
    if inactive:
        _finding(findings, "error", "supported_claim_uses_inactive_evidence", "supported claim relies on inactive evidence: " + ", ".join(inactive), CLAIMS_FILE)


def _validate_accepted_ref(
    root: Path,
    value: Any,
    nodes: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    gates: dict[str, dict[str, Any]],
    active_evidence_ids: set[str],
    findings: list[dict[str, str]],
) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.startswith("accepted/") or ".." in Path(value).parts:
        _finding(findings, "error", "unsafe_accepted_ref", f"invalid accepted ref: {value}", RESEARCH_STATE_FILE)
        return None
    path = root / value
    if path.is_symlink() or not path.is_file():
        _finding(findings, "error", "missing_accepted_artifact", f"accepted artifact does not exist: {value}", RESEARCH_STATE_FILE)
        return None
    artifact = _read_json_for_validation(path, value, findings)
    if not isinstance(artifact, dict):
        return None
    findings.extend(schema_findings("accepted_claim.schema.json", artifact, value))
    _check_ref(artifact.get("node_id"), set(nodes), findings, "unknown_accepted_node", value)
    _check_ref(artifact.get("target_ref"), set(claims), findings, "unknown_accepted_claim", value)
    for ref in artifact.get("gate_result_refs", []):
        _check_ref(ref, set(gates), findings, "unknown_accepted_gate", value)

    node_id = str(artifact.get("node_id") or "")
    decision_id = str(artifact.get("decision_id") or "")
    node = nodes.get(node_id)
    if node is None:
        return None
    result = node.get("result") if isinstance(node.get("result"), dict) else {}
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
    expected = {
        "policy": audit.get("policy"),
        "target_ref": audit.get("target_ref"),
        "gate_result_refs": audit.get("gate_result_refs"),
        "summary": audit.get("summary"),
        "decision_id": node.get("ended_by_decision"),
    }
    if node.get("state") != "closed" or audit.get("verdict") != "accepted":
        _finding(findings, "error", "accepted_artifact_without_audit", "accepted artifact does not belong to a closed accepted audit", value)
    for key, expected_value in expected.items():
        if artifact.get(key) != expected_value:
            _finding(findings, "error", "accepted_artifact_mismatch", f"accepted artifact {key} differs from node audit", value)
    target = claims.get(str(artifact.get("target_ref")))
    if target is not None and target.get("status") != "supported":
        _finding(findings, "error", "accepted_claim_not_supported", "accepted artifact target claim is not supported", value)
    selected_gates = [gates.get(str(ref)) for ref in artifact.get("gate_result_refs", [])]
    inactive = sorted(
        ref
        for row in selected_gates
        if isinstance(row, dict)
        for ref in row.get("evidence_refs", [])
        if ref not in active_evidence_ids
    )
    if inactive:
        _finding(findings, "error", "accepted_audit_uses_inactive_evidence", "accepted audit relies on inactive evidence: " + ", ".join(inactive), value)
    if isinstance(artifact.get("policy"), str) and isinstance(artifact.get("target_ref"), str):
        try:
            validate_audit_gate_results(
                artifact["policy"],
                list(gates.values()),
                list(artifact.get("gate_result_refs", [])),
                target_ref=artifact["target_ref"],
            )
        except GateEvaluationError as exc:
            _finding(findings, "error", "invalid_accepted_artifact", str(exc), value)
    return (node_id, decision_id)


def _check_branch_events(events: Any, nodes: dict[str, dict[str, Any]], findings: list[dict[str, str]]) -> None:
    rows = [row for row in events if isinstance(row, dict)] if isinstance(events, list) else []
    by_node: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        node_id = row.get("node_id")
        if isinstance(node_id, str):
            by_node.setdefault(node_id, []).append(row)
        if node_id not in nodes:
            _finding(findings, "error", "unknown_branch_event_node", f"branch event references unknown node: {node_id}", RESEARCH_STATE_FILE)
    for node_id, node in nodes.items():
        selected = by_node.get(node_id, [])
        if len(selected) != 1:
            _finding(findings, "error", "branch_event_count_mismatch", f"node {node_id} requires exactly one branch event", RESEARCH_STATE_FILE)
            continue
        event = selected[0]
        expected = {
            "parent_node": node.get("parent_node"),
            "decision_id": node.get("created_by_decision"),
            "created_at": node.get("opened_at"),
        }
        for key, expected_value in expected.items():
            if event.get(key) != expected_value:
                _finding(findings, "error", "branch_event_mismatch", f"branch event {key} differs from node.json", RESEARCH_STATE_FILE)


def _read_json_for_validation(path: Path, source: str, findings: list[dict[str, str]]) -> Any | None:
    try:
        return read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _finding(findings, "error", "invalid_json", f"cannot read JSON document: {exc}", source)
        return None


def _check_parent_cycles(nodes: dict[str, dict[str, Any]], findings: list[dict[str, str]]) -> None:
    parents = {node_id: node.get("parent_node") for node_id, node in nodes.items()}
    for start in parents:
        current: Any = start
        seen: set[str] = set()
        while isinstance(current, str) and current in parents:
            if current in seen:
                _finding(findings, "error", "node_parent_cycle", f"node parent cycle detected at {current}", RESEARCH_STATE_FILE)
                break
            seen.add(current)
            current = parents[current]


def _check_claim_cycles(rows: list[dict[str, Any]], findings: list[dict[str, str]]) -> None:
    parents = {str(row.get("claim_id")): row.get("parent_claim_id") for row in rows}
    for start in parents:
        current: Any = start
        seen: set[str] = set()
        while isinstance(current, str) and current in parents:
            if current in seen:
                _finding(findings, "error", "claim_parent_cycle", f"claim parent cycle detected at {current}", CLAIMS_FILE)
                break
            seen.add(current)
            current = parents[current]


def _unique_ids(rows: list[dict[str, Any]], key: str, findings: list[dict[str, str]], source: str) -> set[str]:
    values: set[str] = set()
    for item in rows:
        value = item.get(key)
        if not isinstance(value, str) or not value:
            continue
        if value in values:
            _finding(findings, "error", "duplicate_id", f"duplicate {key}: {value}", source)
        values.add(value)
    return values


def _check_ref(value: Any, known: set[str], findings: list[dict[str, str]], code: str, source: str) -> None:
    if isinstance(value, str) and value not in known:
        _finding(findings, "error", code, f"unknown reference: {value}", source)


def _workspace_file_ref_error(root: Path, value: Any, *, owner_node: str) -> str | None:
    try:
        validate_owner_file_ref(root, value, owner_node=owner_node)
    except WorkspaceRefError as exc:
        return str(exc)
    return None


def _report(root: Path, findings: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": "ts-workspace-validation/3",
        "workspace_root": str(root),
        "valid": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
    }


def _finding(findings: list[dict[str, str]], severity: str, code: str, message: str, path: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message, "path": path})
