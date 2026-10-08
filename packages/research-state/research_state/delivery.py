"""Delivery consumes current research facts and records the exact reported scope."""
import hashlib
import json
from pathlib import Path

from .dependencies import dependency_evaluation


def delivery_snapshot(context, node_id, event, *, root=None):
    node = next((row for row in context.get("nodes", []) if row["id"] == node_id), None)
    if node is None:
        raise ValueError("research_node_required: delivery needs an existing node_id")
    from .requirements import requirements_evaluation
    evaluation = requirements_evaluation(context)
    consumes = node.get("consumes", {})
    requirements = consumes.get("requirement_ids", [])
    artifacts = consumes.get("artifact_refs", [])
    dependencies = dependency_evaluation(context, node)
    if not requirements and not artifacts and not dependencies["dependencies"]:
        raise ValueError("delivery_consumption_required: declare the requirements, material or predecessor Nodes reported by this delivery")
    if event == "study_completed":
        if not evaluation["tracked"]:
            raise ValueError("delivery_requirements_untracked: recover user requirements before claiming the study is complete")
        if not evaluation["satisfied"]:
            raise ValueError("delivery_requirements_unmet: study_completed requires current satisfied requirements")
        if consumes.get("condition") == "observed":
            raise ValueError("delivery_event_mismatch: observed state supports progress or failure notification")
    by_id = {row["id"]: row for row in evaluation["requirements"]}
    if any(ref not in by_id for ref in requirements):
        raise ValueError("delivery_requirement_unknown")
    if consumes.get("condition", "satisfied") == "satisfied" and any(not by_id[ref]["satisfied"] for ref in requirements):
        raise ValueError("delivery_requirements_unmet")
    registry = {row["id"]: row for row in context.get("artifacts", [])}
    if any(ref not in registry for ref in artifacts):
        raise ValueError("delivery_artifact_unknown")
    evidence_basis = {}
    if artifacts:
        if root is None:
            raise ValueError("delivery_workspace_required: verify consumed Artifact versions in their workspace")
        from .assessments import bind_evidence
        evidence_basis = bind_evidence(Path(root), context, artifacts, "")
    # Status events are assertions about explicit consumed work, not free labels.
    scoped_nodes = {row["node_id"] for row in dependencies["dependencies"]}
    scoped_nodes.update(nid for ref in requirements for nid in by_id[ref]["node_ids"])
    producer_ids = set(evidence_basis.get("result_versions", {}))
    attempts = [row for row in context.get("attempts", [])
                if row.get("node_id") in scoped_nodes or row["id"] in producer_ids]
    source_nodes = scoped_nodes | {row["node_id"] for row in attempts if row.get("node_id")}
    source_nodes.update(registry[ref]["node_id"] for ref in artifacts if registry[ref].get("node_id"))
    if event == "calculation_failed" and not any(row.get("state") in {"failed", "timed_out"} for row in attempts):
        raise ValueError("delivery_event_mismatch: no consumed calculation has a confirmed failure")
    if event == "calculation_ambiguous" and not any(row.get("state") == "unknown" or row.get("metadata", {}).get("execution_conflict") for row in attempts):
        raise ValueError("delivery_event_mismatch: no consumed calculation has an ambiguous result")
    if event == "node_completed" and (not dependencies["dependencies"] or any(
            row["state"] != "closed" or row["outcome"] != "completed" for row in dependencies["dependencies"])):
        raise ValueError("delivery_event_mismatch: node_completed requires completed source Nodes")
    snapshot = {"schema_version": "research-delivery-basis/1", "node_id": node_id, "event": event,
                "consumes": consumes,
                "source_nodes": [{"id": row["id"], "state": row.get("state"), "outcome": row.get("outcome"),
                                  "outcome_summary": row.get("outcome_summary")}
                                 for row in sorted(context.get("nodes", []), key=lambda item: item["id"])
                                 if row["id"] in source_nodes],
                "dependencies": dependencies["dependencies"],
                "requirements": [by_id[ref] for ref in sorted(requirements)],
                "artifact_versions": {ref: registry[ref].get("sha256") for ref in sorted(artifacts)},
                "artifact_evidence_basis": evidence_basis,
                "attempts": [{"id": row["id"], "state": row.get("state"),
                              "result_ref": row.get("metadata", {}).get("latest_result_receipt_ref"),
                              "execution_conflict": row.get("metadata", {}).get("execution_conflict")}
                             for row in attempts]}
    if event == "study_completed":
        snapshot["study_requirements"] = evaluation
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": "research-delivery-binding/1", "sha256": "sha256:" + digest, "snapshot": snapshot}
