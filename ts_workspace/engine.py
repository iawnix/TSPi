"""Workspace mutation engine."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any

from .finalizers import compute_v2_close_changes, validate_v2_audit_gates
from .evidence_lifecycle import evidence_lifecycle_view
from .identity import IDENTITY_REF, ensure_workspace_identity
from .io import append_jsonl, now_iso, read_json, sha256_json, write_json, write_text_atomic
from .ontology import NODE_SCHEMA
from .readers import (
    report_branch_context as build_branch_context,
    report_node as build_node_report,
    report_workspace as build_report,
    snapshot_report as build_snapshot,
)
from .state import HYPOTHESES_FILE, RESEARCH_STATE_FILE, initial_hypotheses, initial_research_state
from .validators.decision import ContractError, validate_decision as validate_decision_dict
from .validators.decision_context import validate_decision_for_workspace
from .validators.workspace import REQUIRED_DIRS, REQUIRED_FILES, SOFT_DIRS, validate_workspace as validate_workspace_dict


TRANSACTION_DIR = ".ts-transactions"
WORKSPACE_LOCK = ".ts-workspace.lock"
DRY_RUN_EXCLUDED_DIRS = frozenset({
    ".agents",
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
    root_path = Path(root)
    if decision is not None:
        _require_decision_action(decision, "init_workspace")
        validate_decision_dict(decision)
    elif force:
        raise ContractError("force reinitialize requires an init_workspace decision")
    _require_safe_identity_parent(root_path)
    if not force:
        existing = [
            filename
            for filename in REQUIRED_FILES
            if (root_path / filename).exists() and (root_path / filename).stat().st_size > 0
        ]
        if existing:
            raise ContractError(
                "workspace already initialized: "
                + ", ".join(sorted(existing))
                + "; pass force=True to reinitialize"
            )
    elif root_path.exists():
        _clear_workspace_owned_state(root_path)
    root_path.mkdir(parents=True, exist_ok=True)
    for dirname in REQUIRED_DIRS | SOFT_DIRS:
        (root_path / dirname).mkdir(parents=True, exist_ok=True)

    write_json(root_path / RESEARCH_STATE_FILE, initial_research_state())
    write_json(root_path / "evidence_registry.json", {"schema_version": "ts-evidence-registry", "evidence": []})
    write_json(root_path / HYPOTHESES_FILE, initial_hypotheses())
    (root_path / "decision_log.jsonl").touch()
    identity = ensure_workspace_identity(root_path)

    if decision is not None:
        _commit_transaction(root_path, decision, {}, {"mutation_applied": True})
    return {
        "root": str(root_path),
        "workspace_id": identity["workspace_id"],
        "created": True,
        "valid": validate_workspace_dict(root_path)["valid"],
    }


def update_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_mutation(root, decision, "update_workspace", _update_workspace_once)


def _update_workspace_once(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "update_workspace")
    _require_initialized(root_path)
    payload = decision["payload"]
    appended: dict[str, int] = {"evidence": 0, "provenance": 0}
    changes: dict[Path, Any] = {}

    evidence = payload.get("append_evidence")
    if evidence is not None:
        registry_path = root_path / "evidence_registry.json"
        registry = read_json(registry_path)
        existing = {item["evidence_id"] for item in registry.get("evidence", []) if isinstance(item, dict) and "evidence_id" in item}
        entries = evidence if isinstance(evidence, list) else [evidence]
        for entry in entries:
            if entry["evidence_id"] in existing:
                raise ContractError(f"duplicate evidence_id: {entry['evidence_id']}")
            stored = dict(entry)
            stored.setdefault("created_at", now_iso())
            registry.setdefault("evidence", []).append(stored)
            existing.add(entry["evidence_id"])
            appended["evidence"] += 1
        evidence_lifecycle_view(registry.get("evidence", []))
        changes[registry_path] = registry

    provenance = payload.get("append_provenance")
    if provenance is not None:
        research_path = root_path / RESEARCH_STATE_FILE
        research_state = read_json(research_path)
        items = provenance if isinstance(provenance, list) else [provenance]
        research_state.setdefault("provenance", []).extend(items)
        changes[research_path] = research_state
        appended["provenance"] += len(items)

    repair = payload.get("repair_branch_anchor")
    anchor_repairs = 0
    if repair is not None:
        items = repair if isinstance(repair, list) else [repair]
        for item in items:
            _apply_repair_branch_anchor(root_path, item, _decision_id(decision), changes)
            anchor_repairs += 1

    solution_repair = payload.get("repair_solution_ref")
    solution_repairs = 0
    if solution_repair is not None:
        items = solution_repair if isinstance(solution_repair, list) else [solution_repair]
        for item in items:
            _apply_repair_solution_ref(root_path, item, _decision_id(decision), changes)
            solution_repairs += 1

    repairs = {"branch_anchor": anchor_repairs, "solution_ref": solution_repairs}
    result = {"appended": appended, "repairs": repairs}
    _commit_transaction(root_path, decision, changes, result)
    return result


def start_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_mutation(root, decision, "start_node", _start_node_once)


def _start_node_once(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "start_node")
    _require_initialized(root_path)
    payload = decision["payload"]
    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    node_id = payload.get("node_id") or _next_node_id(research_state)
    node_dir = root_path / "nodes" / node_id
    if (node_dir / "node.json").exists():
        raise ContractError(f"node already exists: {node_id}")
    node_directories = [
        path
        for path in [node_dir] + [
            node_dir / dirname for dirname in ("inputs", "outputs", "scratch", "remote", "attempts")
        ]
        if not path.exists()
    ]

    node = {
        "schema_version": NODE_SCHEMA,
        "node_id": node_id,
        "parent_node": payload.get("parent_node"),
        "node_type": payload["node_type"],
        "objective": payload["objective"],
        "lifecycle": "running",
        "mechanism_action": payload.get("mechanism_action"),
        "candidate_kind": payload.get("candidate_kind"),
        "validation_scope": payload.get("validation_scope"),
        "audit_scope": payload.get("audit_scope"),
        "attempt_kind": payload.get("attempt_kind", "primary"),
        "recalculation_ref": payload.get("recalculation_ref"),
        "expected_evidence": payload.get("expected_evidence", []),
        "evidence_refs": decision.get("evidence_refs", []),
        "hypothesis_ref": payload.get("hypothesis_ref"),
        "proposed_hypothesis": payload.get("proposed_hypothesis"),
        "solution_ref": payload.get("solution_ref"),
        "pathway_ref": payload.get("pathway_ref"),
        "branch_context": payload.get("branch_context"),
        "created_by_decision": _decision_id(decision),
        "started_at": now_iso(),
        "artifacts": {
            "inputs": f"nodes/{node_id}/inputs",
            "outputs": f"nodes/{node_id}/outputs",
            "attempts": f"nodes/{node_id}/attempts",
            "scratch": f"nodes/{node_id}/scratch",
            "remote": f"nodes/{node_id}/remote",
        },
        "closure": None,
    }
    for optional_field in ("mechanism_action", "candidate_kind", "validation_scope", "audit_scope"):
        if node[optional_field] is None:
            node.pop(optional_field)
    tree_entry = {
        key: node.get(key)
        for key in (
            "node_id",
            "parent_node",
            "node_type",
            "objective",
            "lifecycle",
            "mechanism_action",
            "candidate_kind",
            "validation_scope",
            "audit_scope",
            "attempt_kind",
            "recalculation_ref",
            "hypothesis_ref",
            "solution_ref",
            "pathway_ref",
            "branch_context",
        )
        if node.get(key) is not None
    }
    tree_entry["parent_node"] = node.get("parent_node")
    research_state.setdefault("nodes", []).append(tree_entry)
    if node["parent_node"]:
        research_state.setdefault("edges", []).append({"parent_node": node["parent_node"], "child_node": node_id})
    if node["branch_context"]:
        research_state.setdefault("branch_events", []).append(_branch_event_v2(node, decision))
    research_state["current_node"] = node_id

    changes: dict[Path, Any] = {
        node_dir / "node.json": node,
        node_dir / "decision.md": decision["rationale"].strip() + "\n",
        root_path / RESEARCH_STATE_FILE: research_state,
    }
    changes.update(_hypotheses_changes_for_node_start(root_path, node))
    result = {"node_id": node_id, "node_type": node["node_type"], "lifecycle": node["lifecycle"]}
    _commit_transaction(root_path, decision, changes, result, directories=node_directories)
    return result


def end_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_mutation(root, decision, "end_node", _end_node_once)


def _end_node_once(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "end_node")
    _require_initialized(root_path)
    node_id = decision["payload"]["node_id"]
    node_path = root_path / "nodes" / node_id / "node.json"
    node = read_json(node_path)
    closure = dict(decision["payload"]["closure"])
    closure["closed_at"] = now_iso()
    node["closure"] = closure
    node["lifecycle"] = "closed"
    node["ended_by_decision"] = _decision_id(decision)
    node["ended_at"] = closure["closed_at"]
    node["evidence_refs"] = _v2_closure_evidence_refs(node, decision, closure)
    validate_v2_audit_gates(root_path, node, closure, node["evidence_refs"])

    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    for entry in research_state.get("nodes", []):
        if entry.get("node_id") != node_id:
            continue
        entry["lifecycle"] = "closed"
        entry["closed_at"] = closure["closed_at"]
        entry["program_outcome"] = closure["program"]["outcome"]
        if isinstance(closure.get("hypothesis"), dict):
            entry["hypothesis_status"] = closure["hypothesis"]["status"]
        if isinstance(closure.get("audit"), dict):
            entry["audit_status"] = closure["audit"]["status"]
            entry["study_complete"] = closure["audit"]["study_complete"]
        if isinstance(closure.get("intake"), dict):
            entry["intake_status"] = closure["intake"]["status"]
        break
    if research_state.get("current_node") == node_id:
        research_state["current_node"] = None

    changes: dict[Path, Any] = {
        node_path: node,
        root_path / RESEARCH_STATE_FILE: research_state,
    }
    changes.update(compute_v2_close_changes(root_path, node, research_state))
    changes.update(_v2_hypothesis_close_changes(root_path, node, closure))
    result = {"node_id": node_id, "node_type": node["node_type"], "lifecycle": "closed", "closure": closure}
    _commit_transaction(root_path, decision, changes, result)
    return result


def _v2_closure_evidence_refs(
    node: dict[str, Any],
    decision: dict[str, Any],
    closure: dict[str, Any],
) -> list[str]:
    refs = set(str(item) for item in node.get("evidence_refs", []) if item)
    refs.update(str(item) for item in decision.get("evidence_refs", []) if item)
    for section in ("program", "hypothesis", "audit"):
        value = closure.get(section)
        if isinstance(value, dict):
            refs.update(str(item) for item in value.get("evidence_refs", []) if item)
    return sorted(refs)


def _v2_hypothesis_close_changes(root: Path, node: dict[str, Any], closure: dict[str, Any]) -> dict[Path, Any]:
    if node.get("node_type") not in {"mechanism", "audit"}:
        return {}
    model_path = root / HYPOTHESES_FILE
    model = read_json(model_path)
    changed = False
    hypothesis_section = closure.get("hypothesis") if isinstance(closure.get("hypothesis"), dict) else None
    if node.get("node_type") == "mechanism" and hypothesis_section is not None:
        if node.get("mechanism_action") == "propose":
            hypothesis = dict(node["proposed_hypothesis"])
            hypothesis.update(
                {
                    "protocol_version": "ts-hypothesis/2",
                    "status": hypothesis_section["status"],
                    "source_node": node["node_id"],
                    "branch_anchor_node": _v2_branch_anchor(node),
                    "proposed_by_decision": node["created_by_decision"],
                    "evidence_refs": sorted(set(node.get("evidence_refs", []) + hypothesis_section.get("evidence_refs", []))),
                    "prediction_status": [],
                    "assessment_history": [
                        _v2_hypothesis_assessment(node, hypothesis_section)
                    ],
                }
            )
            hypothesis.setdefault("parent_hypothesis_id", None)
            model.setdefault("hypotheses", []).append(hypothesis)
            model["focus_hypothesis_id"] = hypothesis["hypothesis_id"] if hypothesis["status"] != "unsupported" else None
        else:
            hypothesis_id = node["hypothesis_ref"]["hypothesis_id"]
            hypothesis = _find_hypothesis_record(model, hypothesis_id)
            hypothesis["status"] = hypothesis_section["status"]
            hypothesis.setdefault("assessment_history", []).append(_v2_hypothesis_assessment(node, hypothesis_section))
            _append_v2_prediction_status(hypothesis, node, hypothesis_section)
            hypothesis["evidence_refs"] = sorted(set(hypothesis.get("evidence_refs", []) + hypothesis_section.get("evidence_refs", [])))
            model["focus_hypothesis_id"] = hypothesis_id if hypothesis["status"] != "unsupported" else None
            if hypothesis["status"] == "unsupported":
                model.setdefault("refuted_hypotheses", []).append(_v2_hypothesis_assessment(node, hypothesis_section))
        changed = True

    audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else None
    if node.get("node_type") == "audit" and audit is not None:
        record = {
            "node_id": node["node_id"],
            "audit_scope": node.get("audit_scope"),
            "status": audit["status"],
            "study_complete": audit["study_complete"],
            "hypothesis_ref": node.get("hypothesis_ref"),
            "pathway_ref": node.get("pathway_ref"),
            "evidence_refs": audit.get("evidence_refs", []),
            "summary": audit["summary"],
        }
        model.setdefault("audit_records", []).append(record)
        _apply_v2_pathway_audit(model, node, audit)
        changed = True
    return {model_path: model} if changed else {}


def _v2_hypothesis_assessment(node: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    ref = section.get("hypothesis_ref") if isinstance(section.get("hypothesis_ref"), dict) else {}
    return {
        "node_id": node["node_id"],
        "node_type": node["node_type"],
        "status": section["status"],
        "summary": section["summary"],
        "evidence_refs": section.get("evidence_refs", []),
        "revision": section.get("revision"),
        "prediction_ids": ref.get("prediction_ids", []),
    }


def _append_v2_prediction_status(
    hypothesis: dict[str, Any],
    node: dict[str, Any],
    section: dict[str, Any],
) -> None:
    ref = section.get("hypothesis_ref") if isinstance(section.get("hypothesis_ref"), dict) else {}
    prediction_ids = ref.get("prediction_ids", [])
    if not prediction_ids:
        return
    hypothesis.setdefault("prediction_status", []).append(
        {
            "node_id": node["node_id"],
            "node_type": node["node_type"],
            "hypothesis_status": section["status"],
            "prediction_ids": prediction_ids,
            "evidence_refs": section.get("evidence_refs", []),
        }
    )


def _find_hypothesis_record(model: dict[str, Any], hypothesis_id: str) -> dict[str, Any]:
    for hypothesis in model.get("hypotheses", []):
        if isinstance(hypothesis, dict) and hypothesis.get("hypothesis_id") == hypothesis_id:
            return hypothesis
    raise ContractError(f"unknown hypothesis_id: {hypothesis_id}")


def _v2_branch_anchor(node: dict[str, Any]) -> str:
    context = node.get("branch_context") if isinstance(node.get("branch_context"), dict) else {}
    return str(context.get("anchor_node") or node.get("parent_node") or node["node_id"])


def _apply_v2_pathway_audit(model: dict[str, Any], node: dict[str, Any], audit: dict[str, Any]) -> None:
    ref = node.get("pathway_ref") if isinstance(node.get("pathway_ref"), dict) else None
    if not ref:
        return
    pathway_id = ref["pathway_id"]
    pathway = next(
        (item for item in model.setdefault("pathways", []) if item.get("pathway_id") == pathway_id),
        None,
    )
    if pathway is None:
        pathway = {"pathway_id": pathway_id, "label": pathway_id, "pattern": "unspecified", "status": "active", "steps": []}
        model["pathways"].append(pathway)
    pathway.setdefault("audit_nodes", []).append(node["node_id"])
    status = {
        "accepted": "accepted",
        "not_accepted": "refuted",
        "ambiguous": "active",
    }[audit["status"]]
    if node.get("audit_scope") == "elementary_step" and ref.get("step_id"):
        step_id = ref["step_id"]
        step = next((item for item in pathway.setdefault("steps", []) if item.get("step_id") == step_id), None)
        if step is None:
            step = {"step_id": step_id, "from": "unknown", "to": "unknown", "status": "active"}
            pathway["steps"].append(step)
        step["status"] = status
        step.setdefault("audit_nodes", []).append(node["node_id"])
        step_statuses = {item.get("status") for item in pathway["steps"] if isinstance(item, dict)}
        pathway["status"] = (
            "refuted"
            if "refuted" in step_statuses
            else "accepted"
            if step_statuses and step_statuses <= {"accepted"}
            else "active"
        )
    elif node.get("audit_scope") == "pathway":
        pathway["status"] = status
    model["focus_pathway_id"] = pathway_id


def _branch_event_v2(node: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    context = node["branch_context"]
    return {
        "event_id": "br_" + sha256_json({"node_id": node["node_id"], "branch_context": context}).split(":", 1)[1][:10],
        "event_state": "resolved",
        "relation": context["relation"],
        "from_node": context["from_node"],
        "anchor_node": context["anchor_node"],
        "new_node": node["node_id"],
        "parent_node": node.get("parent_node"),
        "is_rebased": node.get("parent_node") == context["anchor_node"] and context["from_node"] != context["anchor_node"],
        "rationale": decision["rationale"],
        "evidence_refs": context.get("evidence_refs", []),
        "target_hypothesis_ref": node.get("hypothesis_ref"),
        "target_solution_ref": node.get("solution_ref"),
        "target_pathway_ref": node.get("pathway_ref"),
        "created_by_decision": _decision_id(decision),
        **({"reason_code": context["reason_code"]} if context.get("reason_code") else {}),
        **({"changed_variable": context["changed_variable"]} if context.get("changed_variable") else {}),
    }


def _apply_mutation(
    root: str | Path,
    decision: dict[str, Any],
    expected_action: str,
    mutation: Any,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    _require_decision_action(decision, expected_action)
    _require_initialized(root_path)
    with _workspace_lock(root_path):
        _recover_incomplete_transactions(root_path)
        replay = _committed_decision_result(root_path, decision)
        if replay is not None:
            return replay
        validate_decision_dry_run(root_path, decision)
        return mutation(root_path, decision)


@contextmanager
def _workspace_lock(root: Path):
    lock_path = root / WORKSPACE_LOCK
    lock_path.touch(mode=0o600, exist_ok=True)
    with lock_path.open("r+", encoding="utf-8") as handle:
        flock(handle.fileno(), LOCK_EX)
        try:
            yield
        finally:
            flock(handle.fileno(), LOCK_UN)


def _committed_decision_result(root: Path, decision: dict[str, Any]) -> dict[str, Any] | None:
    decision_id = _decision_id(decision)
    snapshot_path = root / "decisions" / f"{decision_id}.json"
    status = _transaction_status(root, decision_id)
    if not snapshot_path.exists() and not status:
        return None
    if not snapshot_path.exists():
        raise ContractError(f"decision_id already has {status} transaction without decision snapshot: {decision_id}")
    existing = read_json(snapshot_path)
    if sha256_json(existing) != sha256_json(decision):
        raise ContractError(f"decision_id already exists with different content: {decision_id}")
    if status != "committed":
        raise ContractError(f"decision_id already exists without committed transaction: {decision_id}")
    result = _decision_log_result(root, decision_id)
    if result is None:
        raise ContractError(f"committed decision is missing its decision_log result: {decision_id}")
    return result


def _decision_log_result(root: Path, decision_id: str) -> dict[str, Any] | None:
    path = root / "decision_log.jsonl"
    if not path.exists():
        return None
    result = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("decision_id") == decision_id and isinstance(row.get("result"), dict):
            result = row["result"]
    return result


def _commit_transaction(
    root: Path,
    decision: dict[str, Any],
    changes: dict[Path, Any],
    result: dict[str, Any],
    *,
    directories: list[Path] | None = None,
) -> None:
    """Stage all writes, replace targets, and roll back on any local failure."""
    decision_id = _decision_id(decision)
    snapshot_ref = f"decisions/{decision_id}.json"
    snapshot_path = root / snapshot_ref
    transaction_status = _transaction_status(root, decision_id)
    if snapshot_path.exists():
        existing = read_json(snapshot_path)
        if sha256_json(existing) != sha256_json(decision):
            raise ContractError(f"decision_id already exists with different content: {decision_id}")
        if transaction_status == "committed":
            return
        raise ContractError(f"decision_id already exists without committed transaction: {decision_id}")
    if transaction_status:
        raise ContractError(f"decision_id already has {transaction_status} transaction without decision snapshot: {decision_id}")
    if snapshot_path not in changes:
        changes = {snapshot_path: decision, **changes}

    directories = directories or []
    tx_path = root / "transaction_log.jsonl"
    decision_log_path = root / "decision_log.jsonl"
    decision_log_row = {
        "decision_id": decision_id,
        "created_at": now_iso(),
        "report_ref": decision.get("report_ref"),
        "action": decision["action"],
        "payload_hash": sha256_json(decision.get("payload", {})),
        "evidence_refs": decision.get("evidence_refs", []),
        "snapshot_ref": snapshot_ref,
        "result": result,
    }
    changes[decision_log_path] = _jsonl_with_row(decision_log_path, decision_log_row)
    relative_paths = sorted(str(path.relative_to(root)) for path in changes)
    relative_directories = sorted(str(path.relative_to(root)) for path in directories)
    transaction_root = root / TRANSACTION_DIR / decision_id
    staged_root = transaction_root / "staged"
    backup_root = transaction_root / "backup"
    if transaction_root.exists():
        raise ContractError(f"transaction staging already exists: {decision_id}")
    staged_hashes: dict[str, str] = {}
    original_hashes: dict[str, str | None] = {}
    for path, value in changes.items():
        relative = path.relative_to(root)
        staged = staged_root / relative
        _write_change(staged, value)
        staged_hashes[str(relative)] = _sha256_file(staged)
        original_hashes[str(relative)] = _sha256_file(path) if path.exists() else None

    prepare_row = {
        "decision_id": decision_id,
        "stage": "prepare",
        "created_at": now_iso(),
        "action": decision.get("action"),
        "paths": relative_paths,
        "directories": relative_directories,
        "staged_sha256": staged_hashes,
        "original_sha256": original_hashes,
    }
    append_jsonl(
        tx_path,
        prepare_row,
    )
    transaction_resolved = False
    try:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=False)
        for target in changes:
            relative = target.relative_to(root)
            staged = staged_root / relative
            backup = backup_root / relative
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
        append_jsonl(
            tx_path,
            {
                "decision_id": decision_id,
                "stage": "committed",
                "created_at": now_iso(),
                "action": decision.get("action"),
                "paths": relative_paths,
            },
        )
        transaction_resolved = True
    except Exception as mutation_error:
        try:
            _rollback_transaction(root, prepare_row)
            append_jsonl(
                tx_path,
                {
                    "decision_id": decision_id,
                    "stage": "aborted",
                    "created_at": now_iso(),
                    "action": decision.get("action"),
                    "paths": relative_paths,
                },
            )
            transaction_resolved = True
        except Exception as rollback_error:
            raise ContractError(
                f"transaction {decision_id} failed and automatic rollback was incomplete; "
                f"recovery data is preserved under {TRANSACTION_DIR}/{decision_id}: {rollback_error}"
            ) from mutation_error
        raise
    finally:
        if transaction_resolved:
            shutil.rmtree(transaction_root, ignore_errors=True)


def _write_change(path: Path, value: Any) -> None:
    if isinstance(value, str):
        write_text_atomic(path, value)
    else:
        write_json(path, value)


def _jsonl_with_row(path: Path, row: dict[str, Any]) -> str:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    return existing + json.dumps(row, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _rollback_transaction(root: Path, prepare: dict[str, Any]) -> None:
    decision_id = str(prepare["decision_id"])
    transaction_root = root / TRANSACTION_DIR / decision_id
    backup_root = transaction_root / "backup"
    staged_root = transaction_root / "staged"
    paths, staged_hashes, original_hashes = _validated_recovery_metadata(root, prepare)
    for relative in paths:
        _validate_rollback_target(
            decision_id,
            relative,
            root / relative,
            backup_root / relative,
            staged_hashes[str(relative)],
            original_hashes[str(relative)],
        )
    for relative in reversed(paths):
        target = root / relative
        backup = backup_root / relative
        original_hash = original_hashes.get(str(relative))
        if backup.exists():
            if target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, target)
        elif original_hash is None and target.exists():
            target.unlink()
        staged = staged_root / relative
        if staged.exists():
            staged.unlink()
    for relative_value in reversed(prepare.get("directories", [])):
        directory = root / str(relative_value)
        try:
            directory.rmdir()
        except OSError:
            pass


def _validate_rollback_target(
    decision_id: str,
    relative: Path,
    target: Path,
    backup: Path,
    staged_hash: str,
    original_hash: str | None,
) -> None:
    if backup.exists():
        if original_hash is None or _sha256_file(backup) != original_hash:
            raise ContractError(f"transaction {decision_id} backup does not match its recorded original: {relative}")
        if target.exists() and _sha256_file(target) != staged_hash:
            raise ContractError(f"transaction {decision_id} target changed after prepare: {relative}")
        return
    if original_hash is not None:
        if not target.exists() or _sha256_file(target) != original_hash:
            raise ContractError(f"transaction {decision_id} is missing its recorded backup: {relative}")
        return
    if target.exists() and _sha256_file(target) != staged_hash:
        raise ContractError(f"transaction {decision_id} created target changed after prepare: {relative}")


def _validated_recovery_metadata(
    root: Path,
    prepare: dict[str, Any],
) -> tuple[list[Path], dict[str, str], dict[str, str | None]]:
    decision_id = str(prepare.get("decision_id") or "unknown")
    if not _is_safe_identifier(decision_id):
        raise ContractError(f"transaction has an unsafe decision_id: {decision_id!r}")
    raw_paths = prepare.get("paths")
    staged_hashes = prepare.get("staged_sha256")
    original_hashes = prepare.get("original_sha256")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ContractError(f"transaction {decision_id} lacks recovery paths; manual reconciliation is required")
    if not isinstance(staged_hashes, dict) or not isinstance(original_hashes, dict):
        raise ContractError(
            f"transaction {decision_id} predates recoverable transaction metadata; manual reconciliation is required"
        )

    paths: list[Path] = []
    path_keys: list[str] = []
    for value in raw_paths:
        key = str(value)
        relative = _validated_workspace_relative_path(root, key, decision_id, "path")
        paths.append(relative)
        path_keys.append(key)

    raw_directories = prepare.get("directories", [])
    if not isinstance(raw_directories, list):
        raise ContractError(f"transaction {decision_id} has invalid recovery directories")
    for value in raw_directories:
        _validated_workspace_relative_path(root, str(value), decision_id, "directory")

    if set(staged_hashes) != set(path_keys) or set(original_hashes) != set(path_keys):
        raise ContractError(f"transaction {decision_id} recovery metadata does not cover every target path")
    for key in path_keys:
        if not _is_sha256(staged_hashes.get(key)):
            raise ContractError(f"transaction {decision_id} has an invalid staged hash for {key}")
        original_hash = original_hashes.get(key)
        if original_hash is not None and not _is_sha256(original_hash):
            raise ContractError(f"transaction {decision_id} has an invalid original hash for {key}")
    return paths, staged_hashes, original_hashes


def _validated_workspace_relative_path(root: Path, key: str, decision_id: str, kind: str) -> Path:
    relative = Path(key)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ContractError(f"transaction {decision_id} contains an unsafe recovery {kind}: {key}")
    target = (root / relative).resolve()
    if target == root or root not in target.parents:
        raise ContractError(f"transaction {decision_id} recovery {kind} escapes the workspace: {key}")
    return relative


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.split(":", 1)[1]
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def _is_safe_identifier(value: str) -> bool:
    return (
        1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character.isalnum() or character in "._-" for character in value)
    )


def _recover_incomplete_transactions(root: Path) -> None:
    prepared = _pending_transaction_rows(root)
    for decision_id, row in prepared.items():
        _rollback_transaction(root, row)
        append_jsonl(
            root / "transaction_log.jsonl",
            {
                "decision_id": decision_id,
                "stage": "aborted",
                "created_at": now_iso(),
                "action": row.get("action"),
                "paths": row.get("paths", []),
                "recovered": True,
            },
        )
        shutil.rmtree(root / TRANSACTION_DIR / decision_id, ignore_errors=True)
    transaction_root = root / TRANSACTION_DIR
    if transaction_root.exists():
        for path in transaction_root.iterdir():
            if path.is_dir() and _transaction_latest_stage(root, path.name) in {"committed", "aborted"}:
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_dir():
                raise ContractError(
                    f"transaction staging has no recoverable prepare record: {path.name}; manual reconciliation is required"
                )


def _pending_transaction_rows(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "transaction_log.jsonl"
    if not path.exists():
        return {}
    pending: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        decision_id = row.get("decision_id")
        stage = row.get("stage")
        if not isinstance(decision_id, str):
            continue
        if stage == "prepare":
            pending[decision_id] = row
        elif stage in {"committed", "aborted"}:
            pending.pop(decision_id, None)
    return pending


def _transaction_status(root: Path, decision_id: str) -> str:
    status = _transaction_latest_stage(root, decision_id)
    return "" if status == "aborted" else status


def _transaction_latest_stage(root: Path, decision_id: str) -> str:
    tx_path = root / "transaction_log.jsonl"
    if not tx_path.exists():
        return ""
    status = ""
    for line in tx_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("decision_id") != decision_id:
            continue
        stage = row.get("stage")
        if stage == "prepare":
            status = "prepare"
        elif stage == "committed":
            status = "committed"
        elif stage == "aborted":
            status = "aborted"
    return status


def _clear_workspace_owned_state(root: Path) -> None:
    """Remove files and directories owned by the TS workspace before force reinit."""
    identity_path = _require_safe_identity_parent(root)
    for dirname in sorted(REQUIRED_DIRS | SOFT_DIRS):
        path = root / dirname
        if path.exists():
            shutil.rmtree(path)
    for filename in sorted(REQUIRED_FILES | {"decision_log.jsonl", "transaction_log.jsonl"}):
        path = root / filename
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    transaction_root = root / TRANSACTION_DIR
    if transaction_root.exists():
        shutil.rmtree(transaction_root)
    lock_path = root / WORKSPACE_LOCK
    if lock_path.exists():
        lock_path.unlink()
    if identity_path.exists() or identity_path.is_symlink():
        identity_path.unlink()


def _require_safe_identity_parent(root: Path) -> Path:
    identity_path = root / IDENTITY_REF
    if identity_path.parent.is_symlink():
        raise ContractError(f"workspace identity path cannot contain a symbolic link: {identity_path}")
    return identity_path


def report_workspace(root: str | Path) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_report(root)


def snapshot_report(root: str | Path) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_snapshot(root)


def report_node(root: str | Path, node_id: str) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_node_report(root, node_id)


def report_branch_context(root: str | Path, from_node: str, anchor_node: str) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_branch_context(root, from_node, anchor_node)


def validate_workspace(root: str | Path) -> dict[str, Any]:
    return validate_workspace_dict(root)


def validate_decision_dry_run(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    """Run a mutation decision through its real finalizer on a disposable snapshot."""

    root_path = Path(root).resolve()
    validate_decision_for_workspace(root_path, decision)
    action = str(decision.get("action"))
    mutation = {
        "start_node": _start_node_once,
        "update_workspace": _update_workspace_once,
        "end_node": _end_node_once,
    }.get(action)
    if mutation is None:
        return {"executed": False, "action": action, "reason": "non_mutation_decision"}

    with tempfile.TemporaryDirectory(prefix="ts-workspace-decision-") as temporary:
        snapshot = Path(temporary) / "workspace"
        shutil.copytree(
            root_path,
            snapshot,
            symlinks=True,
            ignore_dangling_symlinks=True,
            ignore=_ignore_dry_run_entries,
        )
        result = mutation(snapshot, decision)
        validation = validate_workspace_dict(snapshot)
        errors = [item for item in validation.get("findings", []) if item.get("severity") == "error"]
        if errors:
            summary = "; ".join(
                f"{item.get('path', '?')}: {item.get('message', item.get('code', 'validation error'))}"
                for item in errors[:8]
            )
            raise ContractError(f"decision dry run produced an invalid workspace: {summary}")
    return {"executed": True, "action": action, "result": result, "workspace_validation": validation}


def _ignore_dry_run_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in DRY_RUN_EXCLUDED_DIRS}


def _require_initialized(root: Path) -> None:
    missing = [filename for filename in REQUIRED_FILES if not (root / filename).exists()]
    if missing:
        raise ContractError(f"workspace is not initialized; missing {', '.join(sorted(missing))}")


def _next_node_id(tree: dict[str, Any]) -> str:
    numbers = []
    for entry in tree.get("nodes", []):
        node_id = entry.get("node_id", "")
        if node_id.startswith("n") and node_id[1:].isdigit():
            numbers.append(int(node_id[1:]))
    return f"n{(max(numbers) + 1) if numbers else 1:03d}"


def _decision_id(decision: dict[str, Any]) -> str:
    if isinstance(decision.get("decision_id"), str) and decision["decision_id"].strip():
        decision_id = decision["decision_id"].strip()
        if not _is_safe_identifier(decision_id):
            raise ContractError(f"decision_id is not a path-safe identifier: {decision_id!r}")
        return decision_id
    return "dec_" + sha256_json(decision).split(":", 1)[1][:12]


def _require_decision_action(decision: dict[str, Any], expected: str) -> None:
    action = decision.get("action") if isinstance(decision, dict) else None
    if action != expected:
        raise ContractError(f"decision action {action!r} does not match command {expected!r}")


def _hypotheses_changes_for_node_start(root: Path, node: dict[str, Any]) -> dict[Path, Any]:
    path = root / HYPOTHESES_FILE
    model = read_json(path)
    changed = _ensure_pathway_for_node(model, node)
    return {path: model} if changed else {}


def _ensure_pathway_for_node(model: dict[str, Any], node: dict[str, Any]) -> bool:
    ref = node.get("pathway_ref")
    if not ref:
        return False
    pathway_id = ref["pathway_id"]
    step_id = ref.get("step_id")
    for pathway in model.setdefault("pathways", []):
        if pathway.get("pathway_id") == pathway_id:
            break
    else:
        pathway = {"pathway_id": pathway_id, "label": pathway_id, "pattern": "unspecified", "status": "active", "steps": []}
        model["pathways"].append(pathway)
    if step_id:
        for step in pathway.setdefault("steps", []):
            if step.get("step_id") == step_id:
                break
        else:
            pathway["steps"].append({"step_id": step_id, "from": "unknown", "to": "unknown", "status": "active"})
    model["focus_pathway_id"] = pathway_id
    return True


def _apply_repair_branch_anchor(
    root: Path,
    repair: dict[str, Any],
    decision_id: str,
    changes: dict[Path, Any],
) -> None:
    node_id = str(repair["node_id"])
    new_anchor = str(repair["new_anchor_node"])
    reason_code = str(repair["reason_code"])
    repaired_at = now_iso()

    node_path = root / "nodes" / node_id / "node.json"
    node = read_json(node_path) if node_path not in changes else changes[node_path]
    old_parent = node.get("parent_node")
    context = dict(node.get("branch_context") or {})
    old_anchor = context.get("anchor_node")
    context["anchor_node"] = new_anchor
    node["parent_node"] = new_anchor
    node["branch_context"] = context
    node.setdefault("lineage_repairs", []).append(
        {
            "decision_id": decision_id,
            "repaired_at": repaired_at,
            "reason_code": reason_code,
            "old_parent_node": old_parent,
            "old_anchor_node": old_anchor,
            "new_parent_node": new_anchor,
            "new_anchor_node": new_anchor,
        }
    )
    changes[node_path] = node

    research_path = root / RESEARCH_STATE_FILE
    research_state = read_json(research_path) if research_path not in changes else changes[research_path]
    for entry in research_state.get("nodes", []):
        if entry.get("node_id") == node_id:
            entry["parent_node"] = new_anchor
            entry["branch_context"] = context
            break
    for edge in research_state.get("edges", []):
        if edge.get("child_node") == node_id:
            edge["parent_node"] = new_anchor
            break
    for event in research_state.get("branch_events", []):
        if event.get("new_node") != node_id:
            continue
        event["anchor_node"] = new_anchor
        event["parent_node"] = new_anchor
        event["is_rebased"] = event.get("from_node") != new_anchor
        event.setdefault("lineage_repairs", []).append(
            {
                "decision_id": decision_id,
                "repaired_at": repaired_at,
                "reason_code": reason_code,
                "old_parent_node": old_parent,
                "old_anchor_node": old_anchor,
                "new_parent_node": new_anchor,
                "new_anchor_node": new_anchor,
            }
        )
        break
    changes[research_path] = research_state


def _apply_repair_solution_ref(
    root: Path,
    repair: dict[str, Any],
    decision_id: str,
    changes: dict[Path, Any],
) -> None:
    node_id = str(repair["node_id"])
    solution_ref = dict(repair["solution_ref"])
    reason_code = str(repair["reason_code"])
    repaired_at = now_iso()
    record = {
        "decision_id": decision_id,
        "repaired_at": repaired_at,
        "reason_code": reason_code,
        "new_solution_ref": solution_ref,
    }

    node_path = root / "nodes" / node_id / "node.json"
    node = read_json(node_path) if node_path not in changes else changes[node_path]
    node["solution_ref"] = solution_ref
    node.setdefault("lineage_repairs", []).append(record)
    changes[node_path] = node

    research_path = root / RESEARCH_STATE_FILE
    research_state = read_json(research_path) if research_path not in changes else changes[research_path]
    tree_entry = next((item for item in research_state.get("nodes", []) if item.get("node_id") == node_id), None)
    if tree_entry is None:
        raise ContractError(f"repair_solution_ref missing research state node: {node_id}")
    tree_entry["solution_ref"] = solution_ref
    event = next((item for item in research_state.get("branch_events", []) if item.get("new_node") == node_id), None)
    if event is None:
        raise ContractError(f"repair_solution_ref missing branch event: {node_id}")
    event["target_solution_ref"] = solution_ref
    event.setdefault("lineage_repairs", []).append(record)
    changes[research_path] = research_state
