"""Workspace mutation engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .finalizers import compute_close_changes, validate_accepted_audit_gates, validate_pathway_audit_gates
from .io import append_jsonl, apply_change, now_iso, read_json, sha256_json, write_json
from .readers import report_workspace as build_report, snapshot_report as build_snapshot
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
        validate_decision_dict(decision)
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
    root_path.mkdir(parents=True, exist_ok=True)
    for dirname in REQUIRED_DIRS | SOFT_DIRS:
        (root_path / dirname).mkdir(parents=True, exist_ok=True)

    write_json(
        root_path / "manifest.json",
        {
            "schema_version": "ts-workspace",
            "created_at": now_iso(),
            "current_focus": None,
            "hypothesis_contract_version": "v3",
            "accepted_ts_refs": [],
            "provenance": [],
        },
    )
    write_json(
        root_path / "tree.json",
        {
            "schema_version": "ts-tree",
            "nodes": [],
            "edges": [],
            "current_node": None,
            "branch_events": [],
        },
    )
    write_json(root_path / "evidence_registry.json", {"schema_version": "ts-evidence-registry", "evidence": []})
    write_json(
        root_path / "mechanism_model.json",
        {
            "schema_version": "ts-mechanism",
            "focus_hypothesis_id": None,
            "hypotheses": [],
            "accepted_facts": [],
            "refuted_hypotheses": [],
            "open_questions": [],
        },
    )
    write_json(root_path / "pathway_model.json", {"schema_version": "ts-pathway", "focus_pathway_id": None, "pathways": []})
    (root_path / "knowledge_base.md").write_text("# Knowledge Base\n\n", encoding="utf-8")
    (root_path / "decision_log.jsonl").touch()

    if decision is not None:
        _commit_transaction(root_path, decision, {}, {"mutation_applied": True})
    return {"root": str(root_path), "created": True, "valid": validate_workspace_dict(root_path)["valid"]}


def start_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    validate_decision_for_workspace(root_path, decision)
    _require_initialized(root_path)
    payload = decision["payload"]
    tree = read_json(root_path / "tree.json")
    node_id = payload.get("node_id") or _next_node_id(tree)
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

    tree.setdefault("nodes", []).append(
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
        tree.setdefault("edges", []).append({"parent_node": node["parent_node"], "child_node": node_id})
    if node["branch_context"]:
        tree.setdefault("branch_events", []).append(_branch_event(node, node["branch_context"], decision))
    tree["current_node"] = node_id

    changes: dict[Path, Any] = {
        node_dir / "node.json": node,
        node_dir / "decision.md": decision["rationale"].strip() + "\n",
        root_path / "tree.json": tree,
    }
    changes.update(_pathway_changes_for_node(root_path, node))
    _commit_transaction(root_path, decision, changes, {"mutation_applied": True, "node_id": node_id})
    return {"node_id": node_id, "phase": node["phase"], "lifecycle": node["lifecycle"]}


def update_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    validate_decision_for_workspace(root_path, decision)
    _require_initialized(root_path)
    payload = decision["payload"]
    appended: dict[str, int] = {"evidence": 0, "knowledge": 0, "provenance": 0}
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

    knowledge = payload.get("append_knowledge")
    if knowledge is not None:
        knowledge_path = root_path / "knowledge_base.md"
        text = knowledge_path.read_text(encoding="utf-8") if knowledge_path.exists() else ""
        if not text:
            text = "# Knowledge Base\n\n"
        for title, body in _knowledge_entries(knowledge):
            text += f"## {title}\n\n{body.strip()}\n\n"
            appended["knowledge"] += 1
        changes[knowledge_path] = text

    provenance = payload.get("append_provenance")
    if provenance is not None:
        manifest_path = root_path / "manifest.json"
        manifest = read_json(manifest_path)
        items = provenance if isinstance(provenance, list) else [provenance]
        manifest.setdefault("provenance", []).extend(items)
        changes[manifest_path] = manifest
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
    root_path = Path(root)
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

    tree = read_json(root_path / "tree.json")
    for entry in tree.get("nodes", []):
        if entry.get("node_id") == node_id:
            entry["lifecycle"] = node["lifecycle"]
            entry["closed_at"] = closure["closed_at"]
            entry["claim_verdict"] = closure["claim_verdict"]
            entry["program_status"] = closure["program_status"]
            break
    if tree.get("current_node") == node_id:
        tree["current_node"] = None

    changes: dict[Path, Any] = {
        node_path: node,
        root_path / "tree.json": tree,
    }
    changes.update(compute_close_changes(root_path, node, decision))
    result = {"mutation_applied": True, "node_id": node_id, "lifecycle": node["lifecycle"]}
    _commit_transaction(root_path, decision, changes, result)
    return {"node_id": node_id, "lifecycle": node["lifecycle"], "closure": closure}


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
    if snapshot_path not in changes:
        changes[snapshot_path] = decision

    if not changes:
        return

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


def report_workspace(root: str | Path) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_report(root)


def snapshot_report(root: str | Path) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_snapshot(root)


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


def _branch_event(node: dict[str, Any], branch_context: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    node_id = node["node_id"]
    parent_node = node.get("parent_node")
    from_node = branch_context["from_node"]
    anchor_node = branch_context["anchor_node"]
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
        "target_hypothesis_ref": node.get("hypothesis_ref"),
        "target_solution_ref": node.get("solution_ref"),
        "created_by_decision": _decision_id(decision),
    }
    for field in ("reason_code", "changed_variable"):
        if branch_context.get(field):
            event[field] = branch_context[field]
    return event


def _pathway_changes_for_node(root: Path, node: dict[str, Any]) -> dict[Path, Any]:
    ref = node.get("pathway_ref")
    if not ref:
        return {}
    path = root / "pathway_model.json"
    model = read_json(path)
    pathway_id = ref["pathway_id"]
    step_id = ref["step_id"]
    for pathway in model.setdefault("pathways", []):
        if pathway.get("pathway_id") == pathway_id:
            break
    else:
        pathway = {"pathway_id": pathway_id, "label": pathway_id, "pattern": "unspecified", "status": "active", "steps": []}
        model["pathways"].append(pathway)
    for step in pathway.setdefault("steps", []):
        if step.get("step_id") == step_id:
            break
    else:
        pathway["steps"].append({"step_id": step_id, "from": "unknown", "to": "unknown", "status": "active"})
    model["focus_pathway_id"] = pathway_id
    return {path: model}


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

    tree_path = root / "tree.json"
    tree = read_json(tree_path) if tree_path not in changes else changes[tree_path]
    for entry in tree.get("nodes", []):
        if entry.get("node_id") == node_id:
            entry["parent_node"] = new_anchor
            entry["branch_context"] = context
            break
    for edge in tree.get("edges", []):
        if edge.get("child_node") == node_id:
            edge["parent_node"] = new_anchor
            break
    for event in tree.get("branch_events", []):
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
    changes[tree_path] = tree


def _knowledge_entries(knowledge: str | dict[str, Any] | list[Any]) -> list[tuple[str, str]]:
    if isinstance(knowledge, str):
        return [("Workspace update", knowledge)]
    if isinstance(knowledge, dict):
        return [(str(knowledge.get("title", "Workspace update")), str(knowledge.get("body", "")))]
    entries = []
    for item in knowledge:
        if isinstance(item, str):
            entries.append(("Workspace update", item))
        elif isinstance(item, dict):
            entries.append((str(item.get("title", "Workspace update")), str(item.get("body", ""))))
    return entries
