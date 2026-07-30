"""Workspace mutation engine."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .finalizers import (
    compute_close_changes,
    compute_v2_close_changes,
    validate_accepted_audit_gates,
    validate_pathway_audit_gates,
    validate_v2_audit_gates,
)
from .io import append_jsonl, apply_change, now_iso, read_json, sha256_json, write_json
from .ontology import DECISION_SCHEMA as DECISION_SCHEMA_V2, NODE_SCHEMA as NODE_SCHEMA_V2
from .readers import (
    report_branch_context as build_branch_context,
    report_node as build_node_report,
    report_workspace as build_report,
    snapshot_report as build_snapshot,
)
from .state import (
    HYPOTHESES_FILE,
    LEGACY_STATE_FILES,
    RESEARCH_STATE_FILE,
    convert_legacy_state,
    initial_hypotheses,
    initial_research_state,
    state_layout,
)
from .schema_validation import validate_contract
from .validators.decision import ContractError, validate_decision as validate_decision_dict
from .validators.decision_context import validate_decision_for_workspace
from .validators.workspace import REQUIRED_DIRS, REQUIRED_FILES, SOFT_DIRS, validate_workspace as validate_workspace_dict


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

    if decision is not None:
        _commit_transaction(root_path, decision, {}, {"mutation_applied": True})
    return {"root": str(root_path), "created": True, "valid": validate_workspace_dict(root_path)["valid"]}


def migrate_workspace_state(root: str | Path) -> dict[str, Any]:
    """Convert a complete legacy root layout and archive its old state files."""

    root_path = Path(root)
    layout = state_layout(root_path)
    if layout == "current":
        return {"root": str(root_path), "migrated": False, "reason": "already_current"}
    if layout != "legacy":
        raise ContractError(f"workspace state migration requires a complete legacy layout; found {layout}")

    archive = root_path / "legacy_state"
    if archive.exists() and any(archive.iterdir()):
        raise ContractError(f"legacy state archive is not empty: {archive}")

    for filename, schema_name in (
        ("manifest.json", "manifest.schema.json"),
        ("tree.json", "tree.schema.json"),
        ("mechanism_model.json", "mechanism.schema.json"),
        ("pathway_model.json", "pathway.schema.json"),
        ("evidence_registry.json", "evidence_registry.schema.json"),
    ):
        validate_contract(schema_name, read_json(root_path / filename))

    research_state, hypotheses = convert_legacy_state(root_path)
    research_state.setdefault("provenance", []).append(
        {
            "kind": "state_model_migration",
            "from_layout": "manifest+tree+mechanism+pathway+knowledge",
            "to_layout": "research_state+hypotheses+evidence_registry",
            "migrated_at": now_iso(),
            "legacy_archive": "legacy_state",
        }
    )
    validate_contract("research_state.schema.json", research_state)
    validate_contract("hypotheses.schema.json", hypotheses)

    write_json(root_path / RESEARCH_STATE_FILE, research_state)
    write_json(root_path / HYPOTHESES_FILE, hypotheses)
    archive.mkdir(parents=True, exist_ok=True)
    for filename in sorted(LEGACY_STATE_FILES):
        source = root_path / filename
        if source.exists():
            shutil.move(str(source), str(archive / filename))

    validation = validate_workspace_dict(root_path)
    return {
        "root": str(root_path),
        "migrated": True,
        "legacy_archive": str(archive),
        "valid": validation["valid"],
        "findings": validation["findings"],
    }


def start_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    if decision.get("schema_version") == DECISION_SCHEMA_V2:
        return _start_node_v2(root, decision)
    root_path = Path(root)
    _require_decision_action(decision, "start_node")
    validate_decision_for_workspace(root_path, decision)
    _require_initialized(root_path)
    payload = decision["payload"]
    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    node_id = payload.get("node_id") or _next_node_id(research_state)
    if (root_path / "nodes" / node_id / "node.json").exists():
        raise ContractError(f"node already exists: {node_id}")

    node_dir = root_path / "nodes" / node_id
    for dirname in ("inputs", "outputs", "scratch", "remote"):
        (node_dir / dirname).mkdir(parents=True, exist_ok=True)

    node = {
        "schema_version": "ts-node",
        "node_id": node_id,
        "parent_node": payload.get("parent_node"),
        "phase": payload["phase"],
        "lifecycle": "running",
        "hypothesis": payload["hypothesis"],
        "expected_evidence": payload.get("expected_evidence", []),
        "evidence_refs": decision.get("evidence_refs", []),
        "pathway_ref": payload.get("pathway_ref"),
        "hypothesis_ref": payload.get("hypothesis_ref"),
        "solution_ref": payload.get("solution_ref"),
        "branch_context": payload.get("branch_context"),
        "initial_mechanism_hypothesis": payload.get("initial_mechanism_hypothesis"),
        "created_by_decision": _decision_id(decision),
        "started_at": now_iso(),
        "artifacts": {
            "inputs": f"nodes/{node_id}/inputs",
            "outputs": f"nodes/{node_id}/outputs",
            "scratch": f"nodes/{node_id}/scratch",
            "remote": f"nodes/{node_id}/remote",
        },
        "closure": None,
    }
    research_state.setdefault("nodes", []).append(
        {
            "node_id": node_id,
            "parent_node": node["parent_node"],
            "phase": node["phase"],
            "lifecycle": node["lifecycle"],
            "hypothesis": node["hypothesis"],
            "hypothesis_ref": node.get("hypothesis_ref"),
            "solution_ref": node.get("solution_ref"),
            "branch_context": node.get("branch_context"),
        }
        )
    if node["parent_node"]:
        research_state.setdefault("edges", []).append({"parent_node": node["parent_node"], "child_node": node_id})
    if node["branch_context"]:
        research_state.setdefault("branch_events", []).append(_branch_event(node, node["branch_context"], decision))
    research_state["current_node"] = node_id

    changes: dict[Path, Any] = {
        node_dir / "node.json": node,
        node_dir / "decision.md": decision["rationale"].strip() + "\n",
        root_path / RESEARCH_STATE_FILE: research_state,
    }
    changes.update(_hypotheses_changes_for_node_start(root_path, node))
    _commit_transaction(root_path, decision, changes, {"mutation_applied": True, "node_id": node_id})
    return {"node_id": node_id, "phase": node["phase"], "lifecycle": node["lifecycle"]}


def propose_hypothesis(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "propose_hypothesis")
    validate_decision_for_workspace(root_path, decision)
    _require_initialized(root_path)

    payload = decision["payload"]
    hypothesis = dict(payload["proposed_hypothesis"])
    context = dict(payload["proposal_context"])
    hypothesis_id = hypothesis["hypothesis_id"]
    decision_id = _decision_id(decision)
    created_at = now_iso()
    evidence_refs = sorted(set(hypothesis.get("evidence_refs", []) + decision.get("evidence_refs", [])))
    context["evidence_refs"] = sorted(set(context.get("evidence_refs", []) + decision.get("evidence_refs", [])))
    context["created_at"] = created_at
    hypothesis.update(
        {
            "status": "proposed",
            "source_node": context["from_node"],
            "branch_anchor_node": context["anchor_node"],
            "proposed_by_decision": decision_id,
            "proposal_context": context,
            "evidence_refs": evidence_refs,
            "prediction_status": [],
        }
    )
    hypothesis.setdefault("parent_hypothesis_id", None)

    model_path = root_path / HYPOTHESES_FILE
    model = read_json(model_path)
    model.setdefault("hypotheses", []).append(hypothesis)
    model["focus_hypothesis_id"] = hypothesis_id
    result = {"mutation_applied": True, "hypothesis_id": hypothesis_id, "status": "proposed"}
    _commit_transaction(root_path, decision, {model_path: model}, result)
    return {"hypothesis_id": hypothesis_id, "status": "proposed"}


def update_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "update_workspace")
    validate_decision_for_workspace(root_path, decision)
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
    repairs = 0
    if repair is not None:
        items = repair if isinstance(repair, list) else [repair]
        for item in items:
            _apply_repair_branch_anchor(root_path, item, _decision_id(decision), changes)
            repairs += 1

    result = {"mutation_applied": True, "appended": appended, "repairs": {"branch_anchor": repairs}}
    _commit_transaction(root_path, decision, changes, result)
    return {"appended": appended, "repairs": {"branch_anchor": repairs}}


def end_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    if decision.get("schema_version") == DECISION_SCHEMA_V2:
        return _end_node_v2(root, decision)
    root_path = Path(root)
    _require_decision_action(decision, "end_node")
    validate_decision_for_workspace(root_path, decision)
    _require_initialized(root_path)
    node_id = decision["payload"]["node_id"]
    node_path = root_path / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise ContractError(f"unknown node: {node_id}")
    node = read_json(node_path)
    if node.get("lifecycle") != "running":
        raise ContractError(f"node is not running: {node_id}")

    closure = dict(decision["payload"]["closure"])
    merged_evidence_refs = sorted(set(node.get("evidence_refs", []) + decision.get("evidence_refs", [])))
    validate_accepted_audit_gates(root_path, node, closure, merged_evidence_refs)
    validate_pathway_audit_gates(root_path, node, closure, merged_evidence_refs)
    closure["closed_at"] = now_iso()
    node["closure"] = closure
    node["lifecycle"] = "stopped" if closure["program_status"] == "stopped" else "closed"
    node["ended_by_decision"] = _decision_id(decision)
    node["ended_at"] = closure["closed_at"]
    node["evidence_refs"] = merged_evidence_refs

    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    for entry in research_state.get("nodes", []):
        if entry.get("node_id") == node_id:
            entry["lifecycle"] = node["lifecycle"]
            entry["closed_at"] = closure["closed_at"]
            entry["claim_verdict"] = closure["claim_verdict"]
            entry["program_status"] = closure["program_status"]
            break
    if research_state.get("current_node") == node_id:
        research_state["current_node"] = None

    changes: dict[Path, Any] = {
        node_path: node,
        root_path / RESEARCH_STATE_FILE: research_state,
    }
    changes.update(compute_close_changes(root_path, node, decision, research_state))
    result = {"mutation_applied": True, "node_id": node_id, "lifecycle": node["lifecycle"]}
    _commit_transaction(root_path, decision, changes, result)
    return {"node_id": node_id, "lifecycle": node["lifecycle"], "closure": closure}


def _start_node_v2(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "start_node")
    validate_decision_for_workspace(root_path, decision)
    _require_initialized(root_path)
    payload = decision["payload"]
    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    node_id = payload.get("node_id") or _next_node_id(research_state)
    node_dir = root_path / "nodes" / node_id
    if (node_dir / "node.json").exists():
        raise ContractError(f"node already exists: {node_id}")
    for dirname in ("inputs", "outputs", "scratch", "remote", "attempts"):
        (node_dir / dirname).mkdir(parents=True, exist_ok=True)

    node = {
        "schema_version": NODE_SCHEMA_V2,
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
    result = {"mutation_applied": True, "node_id": node_id, "node_type": node["node_type"]}
    _commit_transaction(root_path, decision, changes, result)
    return {"node_id": node_id, "node_type": node["node_type"], "lifecycle": node["lifecycle"]}


def _end_node_v2(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    _require_decision_action(decision, "end_node")
    validate_decision_for_workspace(root_path, decision)
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
    result = {"mutation_applied": True, "node_id": node_id, "lifecycle": "closed"}
    _commit_transaction(root_path, decision, changes, result)
    return {"node_id": node_id, "node_type": node["node_type"], "lifecycle": "closed", "closure": closure}


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
        "target_solution_ref": None,
        "created_by_decision": _decision_id(decision),
        **({"reason_code": context["reason_code"]} if context.get("reason_code") else {}),
        **({"changed_variable": context["changed_variable"]} if context.get("changed_variable") else {}),
    }


def _commit_transaction(
    root: Path,
    decision: dict[str, Any],
    changes: dict[Path, Any],
    result: dict[str, Any],
) -> None:
    """Apply proposed writes atomically: prepare marker → state files → decision snapshot → decision_log row → committed marker."""
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

    tx_path = root / "transaction_log.jsonl"
    relative_paths = sorted(str(path.relative_to(root)) for path in changes)
    append_jsonl(
        tx_path,
        {
            "decision_id": decision_id,
            "stage": "prepare",
            "created_at": now_iso(),
            "action": decision.get("action"),
            "paths": relative_paths,
        },
    )
    for path, value in changes.items():
        apply_change(path, value)
    append_jsonl(
        root / "decision_log.jsonl",
        {
            "decision_id": decision_id,
            "created_at": now_iso(),
            "report_ref": decision.get("report_ref"),
            "action": decision["action"],
            "payload_hash": sha256_json(decision.get("payload", {})),
            "evidence_refs": decision.get("evidence_refs", []),
            "snapshot_ref": snapshot_ref,
            "result": result,
        },
    )
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


def _transaction_status(root: Path, decision_id: str) -> str:
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
    return status


def _transaction_committed(root: Path, decision_id: str) -> bool:
    return _transaction_status(root, decision_id) == "committed"


def _clear_workspace_owned_state(root: Path) -> None:
    """Remove files and directories owned by the TS workspace before force reinit."""
    for dirname in sorted(REQUIRED_DIRS | SOFT_DIRS):
        path = root / dirname
        if path.exists():
            shutil.rmtree(path)
    for filename in sorted(REQUIRED_FILES | LEGACY_STATE_FILES | {"decision_log.jsonl", "transaction_log.jsonl"}):
        path = root / filename
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


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
        return decision["decision_id"].strip()
    return "dec_" + sha256_json(decision).split(":", 1)[1][:12]


def _require_decision_action(decision: dict[str, Any], expected: str) -> None:
    action = decision.get("action") if isinstance(decision, dict) else None
    if action != expected:
        raise ContractError(f"decision action {action!r} does not match command {expected!r}")


def _branch_event(node: dict[str, Any], branch_context: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    node_id = node["node_id"]
    parent_node = node.get("parent_node")
    from_node = branch_context["from_node"]
    anchor_node = branch_context["anchor_node"]
    target_hypothesis_ref = node.get("hypothesis_ref")
    if branch_context["relation"] == "new_hypothesis_branch" and not target_hypothesis_ref:
        initial = node.get("initial_mechanism_hypothesis")
        hypothesis_id = initial.get("hypothesis_id") if isinstance(initial, dict) else None
        if hypothesis_id:
            target_hypothesis_ref = {"hypothesis_id": hypothesis_id, "prediction_ids": []}
    event = {
        "event_id": "br_" + sha256_json({"node_id": node_id, "branch_context": branch_context}).split(":", 1)[1][:10],
        "event_state": "resolved",
        "relation": branch_context["relation"],
        "from_node": from_node,
        "anchor_node": anchor_node,
        "new_node": node_id,
        "parent_node": parent_node,
        "is_rebased": parent_node == anchor_node and from_node != anchor_node,
        "rationale": decision["rationale"],
        "evidence_refs": branch_context.get("evidence_refs", []),
        "target_hypothesis_ref": target_hypothesis_ref,
        "target_solution_ref": node.get("solution_ref"),
        "created_by_decision": _decision_id(decision),
    }
    for field in ("reason_code", "changed_variable"):
        if branch_context.get(field):
            event[field] = branch_context[field]
    return event


def _hypotheses_changes_for_node_start(root: Path, node: dict[str, Any]) -> dict[Path, Any]:
    path = root / HYPOTHESES_FILE
    model = read_json(path)
    changed = _activate_hypothesis_for_node(model, node)
    changed = _ensure_pathway_for_node(model, node) or changed
    return {path: model} if changed else {}


def _activate_hypothesis_for_node(model: dict[str, Any], node: dict[str, Any]) -> bool:
    hypothesis_ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    if not hypothesis_id:
        return False
    for hypothesis in model.get("hypotheses", []):
        if not isinstance(hypothesis, dict) or hypothesis.get("hypothesis_id") != hypothesis_id:
            continue
        if hypothesis.get("status") != "proposed":
            return False
        hypothesis["status"] = "active"
        hypothesis["activated_by_node"] = node["node_id"]
        return True
    return False


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
