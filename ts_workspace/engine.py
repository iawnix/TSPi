"""Workspace mutation engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .finalizers import finalize_closed_node, validate_accepted_audit_gates
from .io import append_jsonl, append_markdown, now_iso, read_json, sha256_json, write_json
from .readers import report_workspace as build_report
from .validators.decision import ContractError, validate_decision as validate_decision_dict
from .validators.decision_context import validate_decision_for_workspace
from .validators.workspace import REQUIRED_DIRS, REQUIRED_FILES, validate_workspace as validate_workspace_dict


def init_workspace(root: str | Path, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    root_path = Path(root)
    if decision is not None:
        validate_decision_dict(decision)
    root_path.mkdir(parents=True, exist_ok=True)
    for dirname in REQUIRED_DIRS:
        (root_path / dirname).mkdir(parents=True, exist_ok=True)

    write_json(
        root_path / "manifest.json",
        {
            "schema_version": "ts-workspace",
            "created_at": now_iso(),
            "current_focus": None,
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
            "backtrack_events": [],
        },
    )
    write_json(root_path / "evidence_registry.json", {"schema_version": "ts-evidence-registry", "evidence": []})
    write_json(
        root_path / "mechanism_model.json",
        {
            "schema_version": "ts-mechanism",
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
        _log_decision(root_path, decision, {"mutation_applied": True})
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
        "backtrack": payload.get("backtrack"),
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
    write_json(node_dir / "node.json", node)
    (node_dir / "decision.md").write_text(decision["rationale"].strip() + "\n", encoding="utf-8")

    tree.setdefault("nodes", []).append(
        {
            "node_id": node_id,
            "parent_node": node["parent_node"],
            "phase": node["phase"],
            "lifecycle": node["lifecycle"],
            "hypothesis": node["hypothesis"],
        }
    )
    if node["parent_node"]:
        tree.setdefault("edges", []).append({"parent_node": node["parent_node"], "child_node": node_id})
    if node["backtrack"]:
        tree.setdefault("backtrack_events", []).append(_backtrack_event(node_id, node["backtrack"], decision))
    tree["current_node"] = node_id
    write_json(root_path / "tree.json", tree)

    _ensure_pathway_for_node(root_path, node)
    _log_decision(root_path, decision, {"mutation_applied": True, "node_id": node_id})
    return {"node_id": node_id, "phase": node["phase"], "lifecycle": node["lifecycle"]}


def update_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    validate_decision_dict(decision)
    _require_initialized(root_path)
    payload = decision["payload"]
    appended: dict[str, int] = {"evidence": 0, "knowledge": 0, "provenance": 0}

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
        write_json(registry_path, registry)

    knowledge = payload.get("append_knowledge")
    if knowledge is not None:
        for title, body in _knowledge_entries(knowledge):
            append_markdown(root_path / "knowledge_base.md", title, body)
            appended["knowledge"] += 1

    provenance = payload.get("append_provenance")
    if provenance is not None:
        manifest_path = root_path / "manifest.json"
        manifest = read_json(manifest_path)
        items = provenance if isinstance(provenance, list) else [provenance]
        manifest.setdefault("provenance", []).extend(items)
        write_json(manifest_path, manifest)
        appended["provenance"] += len(items)

    _log_decision(root_path, decision, {"mutation_applied": True, "appended": appended})
    return {"appended": appended}


def end_node(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root)
    validate_decision_dict(decision)
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
    closure["closed_at"] = now_iso()
    node["closure"] = closure
    node["lifecycle"] = "stopped" if closure["program_status"] == "stopped" else "closed"
    node["ended_by_decision"] = _decision_id(decision)
    node["ended_at"] = closure["closed_at"]
    node["evidence_refs"] = merged_evidence_refs
    write_json(node_path, node)

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
    write_json(root_path / "tree.json", tree)

    finalize_closed_node(root_path, node, decision)
    _log_decision(root_path, decision, {"mutation_applied": True, "node_id": node_id, "lifecycle": node["lifecycle"]})
    return {"node_id": node_id, "lifecycle": node["lifecycle"], "closure": closure}


def report_workspace(root: str | Path) -> dict[str, Any]:
    _require_initialized(Path(root))
    return build_report(root)


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


def _log_decision(root: Path, decision: dict[str, Any], result: dict[str, Any]) -> None:
    append_jsonl(
        root / "decision_log.jsonl",
        {
            "decision_id": _decision_id(decision),
            "created_at": now_iso(),
            "report_ref": decision.get("report_ref"),
            "action": decision["action"],
            "payload_hash": sha256_json(decision.get("payload", {})),
            "evidence_refs": decision.get("evidence_refs", []),
            "result": result,
        },
    )


def _backtrack_event(node_id: str, backtrack: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": "bt_" + sha256_json({"node_id": node_id, "backtrack": backtrack}).split(":", 1)[1][:10],
        "event_state": "resolved",
        "from_node": backtrack["from_node"],
        "to_node": backtrack["to_node"],
        "new_branch_node": node_id,
        "reason_code": backtrack["reason_code"],
        "changed_variable": backtrack["changed_variable"],
        "rationale": decision["rationale"],
        "evidence_refs": backtrack.get("evidence_refs", []),
        "created_by_decision": _decision_id(decision),
    }


def _ensure_pathway_for_node(root: Path, node: dict[str, Any]) -> None:
    ref = node.get("pathway_ref")
    if not ref:
        return
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
    write_json(path, model)


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
