"""Read-only workspace projections for the research explorer."""

from __future__ import annotations

import json
import stat
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from ts_agent.workspace.acceptance import project_acceptances
from ts_agent.workspace.associations import derive_claim_node_links
from ts_agent.calculation_contracts import (
    CalculationContractError,
    validate_calculation_contract,
)
from ts_agent.workspace.artifacts import WorkspaceArtifactError, resolve_workspace_artifact_ref
from ts_agent.workspace.candidates import (
    CANDIDATE_FILE_NAME,
    MAX_CANDIDATE_BYTES,
    ObservationCandidateError,
    validate_observation_candidates,
)
from ts_agent.io import read_json
from ts_agent.workspace.locator import locate_research_files
from ts_agent.workspace.operational import operational_snapshot
from ts_agent.workspace.gates import project_gates
from ts_agent.workspace.path_safety import has_symlink_component, lexical_path, path_has_symlink
from ts_agent.workspace.refs import (
    ACTIVITY_ID,
    CALCULATION_ID,
    SUBAGENT_RUN_ID,
    node_sort_key,
    phase_sort_key,
)
from ts_agent.workspace.revision import gate_input_revision, report_id_for_revision, workspace_revision_from_documents
from ts_agent.workspace.trajectory import project_research_trajectory
from ts_agent.workspace.state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    RESEARCH_PHASES_FILE,
    RESEARCH_NODES_FILE,
    RESEARCH_STATE_FILE,
    STATE_FILES,
    VALIDATION_RESULTS_FILE,
    PROOF_SPECS_FILE,
    WORKSPACE_FILE,
    OPTIONAL_STATE_FILES,
    GATE_SPECS_FILE,
    GATE_RESULTS_FILE,
)
from ts_agent.workspace.validator import validate_workspace

from .file_preview import preview_capability
from .research_map import project_research_map


def normalize_workspace(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    """Project canonical graph state and separate operational overlays."""

    root = lexical_path(source_root)
    if path_has_symlink(root):
        raise ValueError(f"workspace root contains a symbolic link: {root}")
    documents = {name: _read_object(root / name, root=root) for name in STATE_FILES}
    for name in OPTIONAL_STATE_FILES:
        if (root / name).exists():
            documents[name] = _read_optional_object(root / name, root=root)
    validation = validate_workspace(root)
    revision = workspace_revision_from_documents(documents)
    state = documents[RESEARCH_STATE_FILE]
    operations = operational_snapshot(root)
    activities = operations["deterministic_activities"]
    agent_runs = operations["agent_runs"]
    attempt_integrity_findings = operations["calculation_attempt_integrity_findings"]
    operational_integrity_findings = operations.get("operational_integrity_findings", [])
    unresolved_controls = [_normalize_control(record) for record in operations["unresolved_controls"]]
    retryable_controls = [_normalize_control(record) for record in operations["retryable_controls"]]
    claims = _objects(documents[CLAIMS_FILE].get("claims"))
    observations = _objects(documents[OBSERVATIONS_FILE].get("observations"))
    proof_specs = _objects(documents[PROOF_SPECS_FILE].get("proofs"))
    validation_results = _objects(documents[VALIDATION_RESULTS_FILE].get("results"))
    findings = _objects(documents[FINDINGS_FILE].get("findings"))
    raw_phases = _objects(documents[RESEARCH_PHASES_FILE].get("phases"))
    nodes = sorted([
        _normalize_node(
            root,
            record,
            observations=observations,
            activities=activities,
            agent_runs=agent_runs,
            calculation_attempts=operations["calculation_attempts"],
            calculation_attempt_integrity_findings=attempt_integrity_findings,
            operational_integrity_findings=operational_integrity_findings,
            unresolved_controls=unresolved_controls,
            retryable_controls=retryable_controls,
        )
        for record in _objects(documents[RESEARCH_NODES_FILE].get("nodes"))
    ], key=lambda record: node_sort_key(str(record.get("node_id") or "")))
    trajectory = project_research_trajectory(root, raw_phases, nodes)
    trajectory_nodes = {
        str(record.get("node_id")): record
        for record in _objects(trajectory.get("nodes"))
        if isinstance(record.get("node_id"), str)
    }
    nodes = [
        {
            **node,
            "dependent_refs": _strings(trajectory_nodes.get(str(node.get("node_id")), {}).get("dependent_refs")),
            "opening_decision": trajectory_nodes.get(str(node.get("node_id")), {}).get("opening_decision"),
            "completion_decision": trajectory_nodes.get(str(node.get("node_id")), {}).get("completion_decision"),
        }
        for node in nodes
    ]
    claim_node_links = derive_claim_node_links(claims, nodes)
    for node in nodes:
        node["related_claim_refs"] = [
            claim_id
            for claim_id, node_id in claim_node_links
            if node_id == node.get("node_id")
        ]
    acceptances = project_acceptances(root, _strings(state.get("acceptance_refs")), documents)
    current_acceptances = [record for record in acceptances if record["current"]]
    focus_node_refs = _strings(state.get("focus_node_refs"))
    focus_phase_refs = {
        str(node["phase_ref"])
        for node in nodes
        if node.get("node_id") in focus_node_refs and isinstance(node.get("phase_ref"), str)
    }
    phases = sorted(
        [
            _normalize_phase(record, nodes=nodes, focused=record.get("phase_id") in focus_phase_refs)
            for record in raw_phases
        ],
        key=lambda record: phase_sort_key(str(record.get("phase_id") or "")),
    )
    gates = project_gates(
        nodes=nodes,
        claims=claims,
        proof_specs=proof_specs,
        validation_results=validation_results,
        findings=findings,
        operational=operations,
        input_revision=gate_input_revision(root),
        gate_specs=_objects(documents.get(GATE_SPECS_FILE, {}).get("specs")),
        gate_results=_objects(documents.get(GATE_RESULTS_FILE, {}).get("results")),
    )
    research_map = project_research_map(
        phases,
        nodes,
        claims,
        _objects(documents[CLAIM_RELATIONS_FILE].get("relations")),
        observations,
        gates=gates,
    )

    return {
        "schema_version": "ts-web-workspace/6",
        "label": label or root.name,
        "workspace": documents[WORKSPACE_FILE],
        "workspace_revision": revision,
        "report_id": report_id_for_revision(revision),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "claim_refs": _strings(state.get("focus_claim_refs")),
            "phase_refs": sorted(focus_phase_refs, key=phase_sort_key),
            "node_refs": focus_node_refs,
        },
        "acceptance_summary": {
            "record_refs": _strings(state.get("acceptance_refs")),
            "current_refs": [str(record["ref"]) for record in current_acceptances],
            "stale_refs": [str(record["ref"]) for record in acceptances if not record["current"]],
        },
        "claims": claims,
        "claim_relations": _objects(documents[CLAIM_RELATIONS_FILE].get("relations")),
        "research_phases": phases,
        "research_nodes": nodes,
        "research_map": research_map,
        "gates": gates,
        "observations": observations,
        "proof_specs": proof_specs,
        "validation_results": validation_results,
        "findings": findings,
        "acceptances": acceptances,
        "current_acceptances": current_acceptances,
        "decisions": _recent_decisions(root / "decision_log.jsonl"),
        "operational_revision": operations["operational_revision"],
        "operational_summary": operations["operational_summary"],
        "deterministic_activities": activities,
        "activity_summaries": operations["activity_summaries"],
        "node_dispatch": operations.get("node_dispatch", []),
        "activity_integrity_findings": operations["activity_integrity_findings"],
        "operational_integrity_findings": operational_integrity_findings,
        "agent_runs": agent_runs,
        "calculation_attempts": operations["calculation_attempts"],
        "calculation_attempt_integrity_findings": attempt_integrity_findings,
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "pending_controls": operations["pending_controls"],
        "unresolved_controls": unresolved_controls,
        "retryable_controls": retryable_controls,
    }


def workspace_summary(
    row: dict[str, Any],
    *,
    view: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = str(row.get("source_root") or "")
    workspace_id = str(row.get("workspace_id") or "")
    label = str(row.get("label") or (Path(source_root).name if source_root else workspace_id))
    if view is None:
        view = normalize_workspace(source_root, label=label)
    focus = _object(view.get("focus"))
    claims = _objects(view.get("claims"))
    phases = _objects(view.get("research_phases"))
    nodes = _objects(view.get("research_nodes"))
    findings = _objects(view.get("findings"))
    return {
        "workspace_id": workspace_id,
        "label": label,
        "available": True,
        "load_error": None,
        "kernel_protocol": _object(view.get("workspace")).get("kernel_protocol"),
        "workspace_revision": view.get("workspace_revision"),
        "valid": bool(view.get("valid")),
        "claim_count": len(claims),
        "phase_count": len(phases),
        "node_count": len(nodes),
        "open_node_count": sum(1 for node in nodes if node.get("status") == "open"),
        "open_finding_count": sum(1 for finding in findings if finding.get("status") == "open"),
        "focus_claim_refs": _strings(focus.get("claim_refs")),
        "focus_node_refs": _strings(focus.get("node_refs")),
        "acceptance_record_count": len(_objects(view.get("acceptances"))),
        "current_acceptance_count": len(_objects(view.get("current_acceptances"))),
    }


def graph_payload(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    return graph_payload_from_view(normalize_workspace(source_root, label=label))


def workspace_snapshot(
    row: dict[str, Any],
    *,
    since_workspace_revision: str | None = None,
    since_operational_revision: str | None = None,
) -> dict[str, Any]:
    """Return one coherent Web snapshot, or only its unchanged revisions."""

    source_root = str(row.get("source_root") or "")
    workspace_id = str(row.get("workspace_id") or "")
    label = str(row.get("label") or (Path(source_root).name if source_root else workspace_id))
    view = normalize_workspace(source_root, label=label)
    workspace_revision = str(view["workspace_revision"])
    operational_revision = str(view["operational_revision"])
    scientific_changed = since_workspace_revision != workspace_revision
    operational_changed = since_operational_revision != operational_revision
    payload = {
        "schema_version": "ts-explorer-workspace-snapshot/1",
        "workspace_id": workspace_id,
        "changed": scientific_changed or operational_changed,
        "scientific_changed": scientific_changed,
        "operational_changed": operational_changed,
        "workspace_revision": workspace_revision,
        "operational_revision": operational_revision,
    }
    if not payload["changed"]:
        return payload
    return {
        **payload,
        "workspace": workspace_summary(row, view=view),
        "view": view,
        "graph": graph_payload_from_view(view),
    }


def research_files_payload(source_root: str | Path, query: str = "") -> dict[str, Any]:
    """Join research records to the authoritative logical artifact catalog."""

    from ts_agent.compute.artifacts import list_calculation_artifacts

    root = lexical_path(source_root)
    if path_has_symlink(root):
        raise ValueError(f"workspace root contains a symbolic link: {root}")
    catalog = list_calculation_artifacts(root)
    payload = locate_research_files(root, query, artifacts=catalog["artifacts"])
    # The workspace locator is also used by the local CLI and includes its
    # physical root for that caller. The Web contract exposes only logical
    # workspace-relative paths.
    payload.pop("workspace_root", None)
    for match in _objects(payload.get("matches")):
        for key in ("artifacts", "files"):
            for row in _objects(match.get(key)):
                row["preview"] = _workspace_file_preview(root, row.get("path"))
    return payload


def graph_payload_from_view(view: dict[str, Any]) -> dict[str, Any]:
    focus = _object(view.get("focus"))
    focus_claims = set(_strings(focus.get("claim_refs")))
    focus_nodes = set(_strings(focus.get("node_refs")))
    acceptances = _objects(view.get("acceptances"))
    current_acceptances = _objects(view.get("current_acceptances"))
    accepted_claims = {
        str(record.get("claim_ref"))
        for record in current_acceptances
        if record.get("claim_ref")
    }
    historically_accepted_claims = {
        str(record.get("claim_ref"))
        for record in acceptances
        if record.get("claim_ref")
    }
    claims = [
        {
            "id": record.get("claim_id"),
            "claim_id": record.get("claim_id"),
            "claim_type": record.get("claim_type"),
            "statement": record.get("statement"),
            "status": record.get("status"),
            "tags": _strings(record.get("tags")),
            "focus": record.get("claim_id") in focus_claims,
            "accepted": record.get("claim_id") in accepted_claims,
            "acceptance_state": (
                "current"
                if record.get("claim_id") in accepted_claims
                else "historical"
                if record.get("claim_id") in historically_accepted_claims
                else "none"
            ),
            "observation_count": len(_strings(record.get("observation_refs"))),
            "proof_spec_count": len(_strings(record.get("proof_spec_refs"))),
            "validation_result_count": len(_strings(record.get("validation_result_refs"))),
            "review_run_count": sum(
                1
                for run in _objects(view.get("agent_runs"))
                if run.get("role") == "review" and record.get("claim_id") in _strings(run.get("claim_refs"))
            ),
        }
        for record in _objects(view.get("claims"))
    ]
    relations = [
        {
            "id": record.get("relation_id"),
            "source": record.get("source_claim_ref"),
            "target": record.get("target_claim_ref"),
            "kind": record.get("relation_type"),
            "rationale": record.get("rationale"),
        }
        for record in _objects(view.get("claim_relations"))
    ]
    claim_node_pairs = derive_claim_node_links(
        _objects(view.get("claims")),
        _objects(view.get("research_nodes")),
    )
    nodes = [
        {
            "id": record.get("node_id"),
            "node_id": record.get("node_id"),
            "title": record.get("title"),
            "phase_ref": record.get("phase_ref"),
            "objective": record.get("objective"),
            "deliverable": record.get("deliverable"),
            "status": record.get("status"),
            "primary_claim_ref": record.get("primary_claim_ref"),
            "tags": _strings(record.get("tags")),
            "claim_refs": _strings(record.get("claim_refs")),
            "related_claim_refs": [
                claim_id
                for claim_id, node_id in claim_node_pairs
                if node_id == record.get("node_id")
            ],
            "dependency_refs": _strings(record.get("dependency_refs")),
            "focus": record.get("node_id") in focus_nodes,
            "outcome": _object(record.get("result")).get("outcome"),
            "activity_count": len(_objects(record.get("activities"))),
            "attempt_integrity_error_count": len(_objects(record.get("attempt_integrity_findings"))),
            "compute_run_count": int(record.get("compute_run_count") or 0),
            "unresolved_control_count": len(_objects(record.get("unresolved_controls"))),
            "retryable_control_count": len(_objects(record.get("retryable_controls"))),
        }
        for record in _objects(view.get("research_nodes"))
    ]
    node_edges = [
        {
            "id": f"dependency:{dependency}:{node['node_id']}",
            "source": dependency,
            "target": node["node_id"],
            "kind": "depends_on",
        }
        for node in nodes
        for dependency in node["dependency_refs"]
    ]
    claim_node_links = [
        {"claim_ref": claim_ref, "node_ref": node_ref}
        for claim_ref, node_ref in claim_node_pairs
    ]
    return {
        "schema_version": "ts-explorer-graph/6",
        "workspace": view.get("workspace"),
        "workspace_revision": view.get("workspace_revision"),
        "operational_revision": view.get("operational_revision"),
        "valid": bool(view.get("valid")),
        "validation_findings": _list(view.get("validation_findings")),
        "focus": focus,
        "phase_roadmap": {
            "phases": _objects(view.get("research_phases")),
            "nodes": nodes,
        },
        "research_map": _object(view.get("research_map")),
        "gates": _object(view.get("gates")),
        "claim_graph": {"nodes": claims, "edges": relations},
        "research_node_dag": {"nodes": nodes, "edges": node_edges},
        "claim_node_links": claim_node_links,
        "semantic_summary": _semantic_summary(view),
        "operational_summary": _object(view.get("operational_summary")),
        "deterministic_activities": _objects(view.get("deterministic_activities")),
        "activity_summaries": _objects(view.get("activity_summaries")),
        "node_dispatch": _objects(view.get("node_dispatch")),
        "activity_integrity_findings": _list(view.get("activity_integrity_findings")),
        "operational_integrity_findings": _list(view.get("operational_integrity_findings")),
        "calculation_attempt_integrity_findings": _list(view.get("calculation_attempt_integrity_findings")),
        "agent_runs": _objects(view.get("agent_runs")),
        "unresolved_controls": _objects(view.get("unresolved_controls")),
        "retryable_controls": _objects(view.get("retryable_controls")),
    }


def claim_payload(source_root: str | Path, claim_id: str, *, label: str | None = None) -> dict[str, Any]:
    view = normalize_workspace(source_root, label=label)
    all_claims = _objects(view.get("claims"))
    all_nodes = _objects(view.get("research_nodes"))
    claim = _find(all_claims, "claim_id", claim_id, "Claim")
    relations = [
        row
        for row in _objects(view.get("claim_relations"))
        if claim_id in {row.get("source_claim_ref"), row.get("target_claim_ref")}
    ]
    related_node_ids = {
        node_ref
        for claim_ref, node_ref in derive_claim_node_links(all_claims, all_nodes)
        if claim_ref == claim_id
    }
    nodes = [row for row in all_nodes if row.get("node_id") in related_node_ids]
    observation_ids = {
        *_strings(claim.get("observation_refs")),
        *(ref for node in nodes for ref in _strings(node.get("observation_refs"))),
    }
    return {
        "schema_version": "ts-explorer-claim/1",
        "claim": claim,
        "claim_gate": _gate_for_target(view, "claim_gates", "target_claim_ref", claim_id),
        "relations": relations,
        "research_nodes": nodes,
        "observations": [
            row for row in _objects(view.get("observations")) if row.get("observation_id") in observation_ids
        ],
        "proof_specs": [
            row for row in _objects(view.get("proof_specs")) if row.get("target_claim_ref") == claim_id
        ],
        "validation_results": [
            row for row in _objects(view.get("validation_results")) if row.get("target_claim_ref") == claim_id
        ],
        "findings": [
            row for row in _objects(view.get("findings")) if claim_id in _strings(row.get("claim_refs"))
        ],
        "acceptances": [
            row for row in _objects(view.get("acceptances")) if row.get("claim_ref") == claim_id
        ],
        "current_acceptances": [
            row for row in _objects(view.get("current_acceptances")) if row.get("claim_ref") == claim_id
        ],
        "review_runs": [
            row
            for row in _objects(view.get("agent_runs"))
            if row.get("role") == "review" and claim_id in _strings(row.get("claim_refs"))
        ],
    }


def node_payload(source_root: str | Path, node_id: str, *, label: str | None = None) -> dict[str, Any]:
    root = lexical_path(source_root)
    if path_has_symlink(root):
        raise ValueError(f"workspace root contains a symbolic link: {root}")
    view = normalize_workspace(root, label=label)
    node = _find(_objects(view.get("research_nodes")), "node_id", node_id, "ResearchNode")
    compute_runs = [
        row
        for row in _objects(view.get("agent_runs"))
        if row.get("role") == "compute" and node_id in _strings(row.get("node_refs"))
    ]
    node = {
        **node,
        "attempts": _calculation_attempts(
            root,
            node_id,
            agent_runs=compute_runs,
            observations=_objects(view.get("observations")),
            indexed_attempts=_objects(view.get("calculation_attempts")),
            include_details=True,
        ),
    }
    dependency_ids = set(_strings(node.get("dependency_refs")))
    all_nodes = _objects(view.get("research_nodes"))
    all_claims = _objects(view.get("claims"))
    related_claim_ids = {
        claim_ref
        for claim_ref, linked_node_id in derive_claim_node_links(all_claims, all_nodes)
        if linked_node_id == node_id
    }
    phase = _find(
        _objects(view.get("research_phases")),
        "phase_id",
        str(node.get("phase_ref") or ""),
        "ResearchPhase",
    )
    return {
        "schema_version": "ts-explorer-research-node/1",
        "research_node": node,
        "node_gate": _gate_for_target(view, "node_gates", "target_node_ref", node_id),
        "phase": phase,
        "dependencies": [row for row in all_nodes if row.get("node_id") in dependency_ids],
        "dependents": [row for row in all_nodes if node_id in _strings(row.get("dependency_refs"))],
        "claims": [
            row for row in all_claims if row.get("claim_id") in related_claim_ids
        ],
        "observations": [
            row
            for row in _objects(view.get("observations"))
            if row.get("created_by_node") == node_id or row.get("observation_id") in _strings(node.get("observation_refs"))
        ],
        "proof_specs": [
            row
            for row in _objects(view.get("proof_specs"))
            if row.get("created_by_node") == node_id or row.get("proof_id") in _strings(node.get("proof_spec_refs"))
        ],
        "validation_results": [
            row
            for row in _objects(view.get("validation_results"))
            if row.get("evaluated_by_node") == node_id or row.get("result_id") in _strings(node.get("validation_result_refs"))
        ],
        "findings": [
            row for row in _objects(view.get("findings")) if node_id in _strings(row.get("node_refs"))
        ],
        "agent_runs": [
            row for row in _objects(view.get("agent_runs")) if node_id in _strings(row.get("node_refs"))
        ],
        "calculation_attempt_integrity_findings": [
            row
            for row in _objects(view.get("calculation_attempt_integrity_findings"))
            if node_id in _strings(row.get("node_refs"))
        ],
        "history": [
            row for row in _objects(view.get("decisions")) if _contains_ref(row, node_id)
        ],
        "files": list_node_files(root, node_id),
        "node_dispatch": [row for row in view.get("node_dispatch", []) if row["node_id"] == node_id],
        "scientific_analyses": _node_analysis_projection(root, node_id),
    }


def _node_analysis_projection(root, node_id):
    from ts_agent.analysis.projection import analysis_projection
    return analysis_projection(root, node_id, limit=32)


def list_node_files(source_root: str | Path, node_id: str) -> dict[str, Any]:
    root = lexical_path(source_root)
    if path_has_symlink(root):
        return {
            "node_id": node_id,
            "files": [],
            "integrity_error": "workspace root contains a symbolic link",
        }
    node_dir = root / "nodes" / node_id
    if has_symlink_component(root, node_dir) or not node_dir.is_dir() or node_dir.is_symlink():
        return {"node_id": node_id, "files": []}
    files: list[dict[str, Any]] = []
    for path in sorted(node_dir.rglob("*")):
        if has_symlink_component(root, path) or path.is_symlink() or not path.is_file():
            continue
        if not _is_current_node_file(path.relative_to(node_dir).parts):
            continue
        stat = path.stat()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "name": path.name,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
                "preview": preview_capability(path, size=stat.st_size),
            }
        )
    return {"node_id": node_id, "files": files}


def _is_current_node_file(parts: tuple[str, ...]) -> bool:
    if not parts:
        return False
    if parts[0] == "agent-runs":
        return False
    if parts[0] == "activities":
        return len(parts) >= 3 and ACTIVITY_ID.fullmatch(parts[1]) is not None
    if parts[0] != "attempts":
        return True
    if len(parts) < 3 or CALCULATION_ID.fullmatch(parts[1]) is None:
        return False
    if parts[2] != "runs":
        return True
    return len(parts) >= 5 and SUBAGENT_RUN_ID.fullmatch(parts[3]) is not None


def _workspace_file_preview(root: Path, value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        return {"available": False, "reason": "File path is unavailable"}
    parts = Path(value.replace("\\", "/")).parts
    if (
        len(parts) < 3
        or parts[0] != "nodes"
        or not _is_current_node_file(tuple(parts[2:]))
        or ".." in parts
    ):
        return {"available": False, "reason": "File is outside the ResearchNode preview scope"}
    candidate = root / value
    if has_symlink_component(root, candidate) or candidate.is_symlink():
        return {"available": False, "reason": "File is not readable"}
    path = candidate
    if (
        root not in path.parents
        or has_symlink_component(root, candidate)
        or candidate.is_symlink()
        or not path.is_file()
    ):
        return {"available": False, "reason": "File is not readable"}
    return preview_capability(path)


def _normalize_node(
    root: Path,
    record: dict[str, Any],
    *,
    observations: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    agent_runs: list[dict[str, Any]],
    calculation_attempts: list[dict[str, Any]],
    calculation_attempt_integrity_findings: list[dict[str, Any]],
    operational_integrity_findings: list[dict[str, Any]],
    unresolved_controls: list[dict[str, Any]],
    retryable_controls: list[dict[str, Any]],
) -> dict[str, Any]:
    node_id = str(record.get("node_id") or "")
    node_runs = [
        row
        for row in agent_runs
        if row.get("role") == "compute" and node_id in _strings(row.get("node_refs"))
    ]
    attempts = _calculation_attempts(
        root,
        node_id,
        agent_runs=node_runs,
        observations=observations,
        indexed_attempts=calculation_attempts,
    )
    return {
        **record,
        "attempts": attempts,
        "attempt_integrity_findings": [
            row
            for row in calculation_attempt_integrity_findings
            if node_id in _strings(row.get("node_refs"))
        ],
        "operational_integrity_findings": [
            row
            for row in operational_integrity_findings
            if node_id in _strings(row.get("node_refs"))
        ],
        "attempt_summary": {
            "attempt_count": len(attempts),
            "family_count": len({str(item.get("family_root_id")) for item in attempts}),
            "states": _counts(attempts, "display_state"),
        },
        "activities": [row for row in activities if node_id in _strings(row.get("node_refs"))],
        "compute_run_count": sum(
            int(attempt.get("run_count") or 0)
            for attempt in attempts
        ),
        "unresolved_controls": [
            row for row in unresolved_controls if row.get("node_id") == node_id
        ],
        "retryable_controls": [
            row for row in retryable_controls if row.get("node_id") == node_id
        ],
    }


def _normalize_phase(
    record: dict[str, Any],
    *,
    nodes: list[dict[str, Any]],
    focused: bool,
) -> dict[str, Any]:
    phase_id = str(record.get("phase_id") or "")
    phase_nodes = [node for node in nodes if node.get("phase_ref") == phase_id]
    return {
        **record,
        "node_refs": [str(node["node_id"]) for node in phase_nodes],
        "node_count": len(phase_nodes),
        "open_node_count": sum(1 for node in phase_nodes if node.get("status") == "open"),
        "node_statuses": _counts(phase_nodes, "status"),
        "focused": focused,
    }


def _normalize_control(record: dict[str, Any]) -> dict[str, Any]:
    """Give one projected control effect a stable identity within the Web view."""

    intent_id = str(record.get("intent_id") or "unknown-intent")
    operation = str(record.get("operation") or "unknown-operation")
    attempt = record.get("attempt") if isinstance(record.get("attempt"), int) else 1
    return {**record, "control_id": f"{intent_id}:{operation}:{attempt}"}


def _calculation_attempts(
    root: Path,
    node_id: str,
    *,
    agent_runs: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    indexed_attempts: list[dict[str, Any]] | None = None,
    include_details: bool = False,
) -> list[dict[str, Any]]:
    if not node_id:
        return []
    if indexed_attempts is None:
        indexed_attempts = _objects(operational_snapshot(root).get("calculation_attempts"))
    node_rows = [
        row
        for row in indexed_attempts
        if row.get("node_id") == node_id
        and CALCULATION_ID.fullmatch(str(row.get("intent_id") or "")) is not None
    ]
    attempts: list[dict[str, Any]] = []
    for indexed in sorted(
        node_rows,
        key=lambda row: _calculation_path_sort_key(Path(str(row.get("intent_id") or ""))),
    ):
        intent_id = str(indexed["intent_id"])
        attempt_dir = root / "nodes" / node_id / "attempts" / intent_id
        physical_attempt = (
            attempt_dir.is_dir()
            and not attempt_dir.is_symlink()
            and not has_symlink_component(root, attempt_dir)
        )
        result = (
            _read_optional_object(
                attempt_dir / "outputs" / "calculation_result.json",
                root=root,
            )
            if physical_attempt
            else {}
        )
        status = (
            _read_optional_object(attempt_dir / "status.json", root=root)
            if physical_attempt
            else {}
        )
        intent = (
            _read_optional_object(attempt_dir / "intent.json", root=root)
            if physical_attempt
            else {}
        )
        intent_status, intent_error = _calculation_intent_status(intent)
        # The explorer has one public calculation contract.  In particular, it
        # must not silently translate retired ``settings`` or
        # ``recalculation_ref`` fields into the current names.  Keeping those
        # records visible with an explicit status is useful for diagnosis while
        # avoiding a misleading claim that the old record is executable.
        parameters = _object(intent.get("parameters")) if intent_status == "valid" else {}
        lineage = _normalized_attempt_lineage(intent) if intent_status == "valid" else None
        result_provenance = _object(result.get("provenance"))
        status_provenance = _object(status.get("provenance"))
        provenance = status_provenance or result_provenance
        program_record = _object(provenance.get("program_record"))
        runs = [
            row
            for row in agent_runs
            if row.get("role") == "compute" and row.get("intent_id") == intent_id
        ]
        attempt = {
            "intent_id": intent_id,
            "node_id": node_id,
            "ref": attempt_dir.relative_to(root).as_posix(),
            "intent_schema_version": _optional_string(intent.get("schema_version")),
            "intent_status": intent_status,
            "intent_error": intent_error,
            "capability": _optional_string(intent.get("capability")),
            "capability_version": _optional_string(intent.get("capability_version")),
            "expected_output_roles": _strings(intent.get("expected_output_roles")),
            "purpose": _optional_string(intent.get("purpose")),
            "attempt_kind": _optional_string(intent.get("attempt_kind")) or "primary",
            "lineage": lineage,
            "method": _optional_string(parameters.get("method")),
            "basis": _optional_string(parameters.get("basis")),
            "state": indexed.get("state"),
            "program_status": indexed.get("program_status"),
            "error_class": result.get("error_class") or status.get("error_class"),
            "job_id": indexed.get("job_id"),
            "terminal": indexed.get("terminal") is True,
            "blocks_completion": indexed.get("blocks_completion") is True,
            "integrity_error": _optional_string(indexed.get("integrity_error")),
            "started_at": _optional_string(program_record.get("started_at")),
            "finished_at": _optional_string(program_record.get("finished_at")),
            "observed_at": _optional_string(provenance.get("observed_at")),
            "duration_seconds": _duration_seconds(
                _optional_string(program_record.get("started_at")),
                _optional_string(program_record.get("finished_at")),
            ),
            "node_contract_digest": _optional_string(intent.get("node_contract_digest")),
            "scientific_intent_digest": _optional_string(intent.get("scientific_intent_digest")),
            "run_count": len(runs),
        }
        if intent_status == "valid" and not attempt["integrity_error"]:
            candidate_projection = _observation_candidate_projection(
                root,
                attempt_dir,
                intent=intent,
                result=result,
                observations=observations,
            )
            if candidate_projection is not None:
                attempt["observation_candidates"] = candidate_projection
        if include_details:
            execution_target = _object(intent.get("execution_target"))
            attempt.update(
                {
                    "parameters": parameters,
                    "executor": {
                        "backend": _optional_string(intent.get("backend")),
                        "task_type": _optional_string(intent.get("task_type")),
                    },
                    "input_bindings": [
                        {
                            "input_role": _optional_string(binding.get("input_role")),
                            "artifact_id": _optional_string(binding.get("artifact_id")),
                            "source_intent_id": _optional_string(binding.get("source_intent_id")),
                        }
                        for binding in _objects(intent.get("input_bindings"))
                    ],
                    "expected_artifacts": _strings(intent.get("expected_artifacts")),
                    "execution_target": {
                        "kind": _optional_string(execution_target.get("kind")),
                        "profile": _optional_string(execution_target.get("profile")),
                        "resources": _object(execution_target.get("resources")),
                    } if execution_target else None,
                    "runs": runs,
                }
            )
        attempts.append(attempt)
    return _attach_attempt_families(attempts, node_id)


def _observation_candidate_projection(
    root: Path,
    attempt_dir: Path,
    *,
    intent: dict[str, Any],
    result: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Expose bounded parser candidates without promoting them to science."""

    candidate_path = attempt_dir / "outputs" / "parsed" / CANDIDATE_FILE_NAME
    ref = candidate_path.relative_to(root).as_posix()
    projection: dict[str, Any] = {
        "status": "invalid",
        "source": "parser",
        "pending_interpretation": True,
        "ref": ref,
        "candidate_count": 0,
        "candidates": [],
        "diagnostics": [],
    }
    try:
        candidate_mode = candidate_path.lstat().st_mode
    except FileNotFoundError:
        # Older or failed Attempts have no candidate stream to display.
        return None
    except OSError as exc:
        projection["error"] = f"cannot inspect candidate output: {exc}"
        return projection
    if has_symlink_component(root, candidate_path) or stat.S_ISLNK(candidate_mode):
        projection["error"] = "candidate output is not a regular file"
        return projection
    if not stat.S_ISREG(candidate_mode):
        projection["error"] = "candidate output is not a regular file"
        return projection
    try:
        if candidate_path.stat().st_size > MAX_CANDIDATE_BYTES:
            raise ObservationCandidateError(
                f"candidate output exceeds {MAX_CANDIDATE_BYTES} bytes"
            )
        artifact = resolve_workspace_artifact_ref(root, ref)
        document = read_json(candidate_path)
        validate_observation_candidates(document)
    except (OSError, ValueError, WorkspaceArtifactError, ObservationCandidateError) as exc:
        projection["error"] = str(exc)
        return projection

    expected_ref = _optional_string(_object(result.get("provenance")).get("observation_candidates_ref"))
    expected_digest = _optional_string(_object(result.get("provenance")).get("observation_candidates_sha256"))
    if expected_ref != ref or expected_digest != artifact["sha256"]:
        projection["error"] = "candidate output is not bound by the calculation result"
        projection["artifact_id"] = artifact["artifact_id"]
        projection["sha256"] = artifact["sha256"]
        return projection
    if (
        document.get("intent_id") != intent.get("intent_id")
        or document.get("node_id") != intent.get("node_id")
        or document.get("capability") != intent.get("capability")
        or document.get("capability_version") != intent.get("capability_version")
    ):
        projection["error"] = "candidate output binding differs from the calculation intent"
        projection["artifact_id"] = artifact["artifact_id"]
        projection["sha256"] = artifact["sha256"]
        return projection

    candidates = _objects(document.get("candidates"))
    promoted = _candidate_promotions(observations, str(artifact["artifact_id"]))
    candidate_summaries = [
        _candidate_summary(candidate, promoted.get(str(candidate.get("candidate_id") or ""), []))
        for candidate in candidates[:32]
    ]
    promoted_count = sum(1 for candidate in candidates if str(candidate.get("candidate_id") or "") in promoted)
    candidate_status = (
        "empty"
        if not candidates
        else "pending_interpretation"
        if promoted_count < len(candidates)
        else "interpreted"
    )
    projection.update(
        {
            "status": candidate_status,
            "pending_interpretation": promoted_count < len(candidates),
            "artifact_id": artifact["artifact_id"],
            "sha256": artifact["sha256"],
            "intent_id": document.get("intent_id"),
            "node_id": document.get("node_id"),
            "capability": document.get("capability"),
            "capability_version": document.get("capability_version"),
            "parser": _object(document.get("parser")),
            "candidate_count": len(candidates),
            "promoted_count": promoted_count,
            "pending_count": len(candidates) - promoted_count,
            "diagnostics": _bounded_strings(document.get("diagnostics"), 8, 300),
            "candidates": candidate_summaries,
        }
    )
    return projection


def _candidate_promotions(
    observations: list[dict[str, Any]],
    artifact_id: str,
) -> dict[str, list[str]]:
    promoted: dict[str, list[str]] = {}
    for observation in observations:
        binding = _object(observation.get("candidate_ref"))
        candidate_id = _optional_string(binding.get("candidate_id"))
        observation_id = _optional_string(observation.get("observation_id"))
        if binding.get("artifact_id") != artifact_id or not candidate_id or not observation_id:
            continue
        promoted.setdefault(candidate_id, []).append(observation_id)
    return promoted


def _candidate_summary(
    candidate: dict[str, Any],
    observation_refs: list[str],
) -> dict[str, Any]:
    """Keep Web candidate rows useful while bounding parser-controlled values."""

    summary = {
        "candidate_id": candidate.get("candidate_id"),
        "concept_id": candidate.get("concept_id"),
        "subject_ref": str(candidate.get("subject_ref") or "")[:256],
        "datatype": candidate.get("datatype"),
        "unit": candidate.get("unit"),
        "summary": str(candidate.get("summary") or "")[:300],
        "value": _candidate_value_preview(candidate.get("value")),
        "state": "promoted" if observation_refs else "pending_interpretation",
        "observation_refs": observation_refs,
    }
    return summary


def _candidate_value_preview(value: Any) -> Any:
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        return value[:512]
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "<unserializable>"
    if len(encoded) <= 512:
        return value
    return encoded[:509] + "..."


def _bounded_strings(value: Any, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item[:max_length] for item in value if isinstance(item, str) and item][:max_items]


def _normalized_attempt_lineage(intent: dict[str, Any]) -> dict[str, Any] | None:
    current = _object(intent.get("lineage"))
    if current:
        return {
            "source_node": _optional_string(current.get("source_node")),
            "source_intent_id": _optional_string(current.get("source_intent_id")),
            "relation": _optional_string(current.get("relation")),
            "reason": _optional_string(current.get("reason")),
            "changed_fields": _strings(current.get("changed_fields")),
        }
    return None


def _calculation_intent_status(intent: dict[str, Any]) -> tuple[str, str | None]:
    """Classify one Attempt intent without translating retired contracts.

    Web is a read-only projection, but it still needs a trustworthy boundary:
    only the current ``ts-calculation-intent/7`` schema is projected as a
    normal Attempt.  Retired schema versions are ``unsupported`` and malformed
    or incomplete current records are ``invalid``.  The error is deliberately
    bounded because intent files are operator-controlled input.
    """

    if not intent:
        return "invalid", "intent.json is missing, unreadable, or not a JSON object"
    schema_version = intent.get("schema_version")
    if schema_version != "ts-calculation-intent/7":
        return (
            "unsupported",
            f"unsupported calculation intent schema_version: {schema_version!r}; expected 'ts-calculation-intent/7'",
        )
    try:
        validate_calculation_contract("calculation_intent.schema.json", intent)
    except CalculationContractError as exc:
        message = str(exc)
        return "invalid", message[:1000]
    return "valid", None


def _attach_attempt_families(attempts: list[dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    by_id = {str(item.get("intent_id")): item for item in attempts}
    roots: list[str] = []
    for attempt in attempts:
        current = attempt
        visited: set[str] = set()
        depth = 0
        while True:
            current_id = str(current.get("intent_id") or "")
            if current_id in visited:
                break
            visited.add(current_id)
            lineage = _object(current.get("lineage"))
            source_id = _optional_string(lineage.get("source_intent_id"))
            source_node = _optional_string(lineage.get("source_node"))
            if source_node != node_id or source_id not in by_id:
                break
            current = by_id[source_id]
            depth += 1
        root_id = str(current.get("intent_id") or attempt.get("intent_id") or "")
        if root_id not in roots:
            roots.append(root_id)
        attempt["family_root_id"] = root_id
        attempt["family_index"] = roots.index(root_id) + 1
        attempt["lineage_depth"] = depth
        attempt["display_state"] = _attempt_display_state(attempt)
    return attempts


def _attempt_display_state(attempt: dict[str, Any]) -> str:
    intent_status = str(attempt.get("intent_status") or "").lower()
    if intent_status in {"unsupported", "invalid"}:
        return intent_status
    if attempt.get("integrity_error"):
        return "invalid"
    program_status = str(attempt.get("program_status") or "").lower()
    if program_status in {"completed", "failed", "stopped"}:
        return program_status
    return str(attempt.get("state") or program_status or "unknown")


def _duration_seconds(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((finished - started).total_seconds()))


def _calculation_path_sort_key(path: Path) -> tuple[int, str]:
    if CALCULATION_ID.fullmatch(path.name):
        return (int(path.name.removeprefix("calc_")), "")
    return (2**63 - 1, path.name)


def _recent_decisions(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return list(rows)


def _semantic_summary(view: dict[str, Any]) -> dict[str, Any]:
    claims = _objects(view.get("claims"))
    phases = _objects(view.get("research_phases"))
    nodes = _objects(view.get("research_nodes"))
    results = _objects(view.get("validation_results"))
    findings = _objects(view.get("findings"))
    return {
        "claim_count": len(claims),
        "claim_statuses": _counts(claims, "status"),
        "phase_count": len(phases),
        "node_count": len(nodes),
        "node_statuses": _counts(nodes, "status"),
        "observation_count": len(_objects(view.get("observations"))),
        "proof_spec_count": len(_objects(view.get("proof_specs"))),
        "validation_result_count": len(results),
        "validation_verdicts": _counts(results, "verdict"),
        "finding_count": len(findings),
        "open_finding_count": sum(1 for row in findings if row.get("status") == "open"),
        "acceptance_record_count": len(_objects(view.get("acceptances"))),
        "current_acceptance_count": len(_objects(view.get("current_acceptances"))),
    }


def _counts(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _contains_ref(value: Any, reference: str) -> bool:
    if value == reference:
        return True
    if isinstance(value, dict):
        return any(_contains_ref(item, reference) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item, reference) for item in value)
    return False


def _find(records: list[dict[str, Any]], key: str, value: str, label: str) -> dict[str, Any]:
    record = next((row for row in records if row.get(key) == value), None)
    if record is None:
        raise ValueError(f"unknown {label}: {value}")
    return record


def _read_object(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    if root is not None and (has_symlink_component(root, path) or path.is_symlink()):
        raise ValueError(f"workspace file contains a symbolic link: {path.name}")
    try:
        value = read_json(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read workspace file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"workspace file is not an object: {path.name}")
    return value


def _read_optional_object(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    if (
        (root is not None and has_symlink_component(root, path))
        or not path.is_file()
        or path.is_symlink()
    ):
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _gate_for_target(
    view: dict[str, Any],
    collection: str,
    target_key: str,
    target_ref: str,
) -> dict[str, Any] | None:
    gates = _object(view.get("gates"))
    for row in _objects(gates.get(collection)):
        result = _object(row.get("result"))
        if result.get(target_key) == target_ref:
            return row
    return None


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
