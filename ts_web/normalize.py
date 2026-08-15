"""Read-only v4 workspace projections for the research explorer."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from ts_workspace.acceptance import project_acceptances
from ts_workspace.io import read_json
from ts_workspace.operational import operational_snapshot
from ts_workspace.revision import report_id_for_revision, workspace_revision_from_documents
from ts_workspace.state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    RESEARCH_ACTS_FILE,
    RESEARCH_STATE_FILE,
    STATE_FILES,
    VALIDATION_RESULTS_FILE,
    VALIDATION_SPECS_FILE,
    WORKSPACE_FILE,
)
from ts_workspace.validator import validate_workspace


def normalize_workspace(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    """Project canonical v4 graph state and separate operational overlays."""

    root = Path(source_root).expanduser().resolve()
    documents = {name: _read_object(root / name) for name in STATE_FILES}
    validation = validate_workspace(root)
    revision = workspace_revision_from_documents(documents)
    state = documents[RESEARCH_STATE_FILE]
    operations = operational_snapshot(root)
    activities = operations["deterministic_activities"]
    reviews = operations["review_runs"]
    controls = operations["unresolved_controls"]
    acts = [
        _normalize_act(root, record, activities=activities, reviews=reviews, controls=controls)
        for record in _objects(documents[RESEARCH_ACTS_FILE].get("acts"))
    ]
    acceptances = project_acceptances(root, _strings(state.get("acceptance_refs")), documents)
    current_acceptances = [record for record in acceptances if record["current"]]

    return {
        "schema_version": "ts-web-workspace/4",
        "label": label or root.name,
        "source_root": str(root),
        "workspace": documents[WORKSPACE_FILE],
        "workspace_revision": revision,
        "report_id": report_id_for_revision(revision),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "claim_refs": _strings(state.get("focus_claim_refs")),
            "act_refs": _strings(state.get("focus_act_refs")),
        },
        "acceptance_summary": {
            "record_refs": _strings(state.get("acceptance_refs")),
            "current_refs": [str(record["ref"]) for record in current_acceptances],
            "stale_refs": [str(record["ref"]) for record in acceptances if not record["current"]],
        },
        "claims": _objects(documents[CLAIMS_FILE].get("claims")),
        "claim_relations": _objects(documents[CLAIM_RELATIONS_FILE].get("relations")),
        "research_acts": acts,
        "observations": _objects(documents[OBSERVATIONS_FILE].get("observations")),
        "validation_specs": _objects(documents[VALIDATION_SPECS_FILE].get("specs")),
        "validation_results": _objects(documents[VALIDATION_RESULTS_FILE].get("results")),
        "findings": _objects(documents[FINDINGS_FILE].get("findings")),
        "acceptances": acceptances,
        "current_acceptances": current_acceptances,
        "decisions": _recent_decisions(root / "decision_log.jsonl"),
        "operational_revision": operations["operational_revision"],
        "operational_summary": operations["operational_summary"],
        "deterministic_activities": activities,
        "review_runs": reviews,
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "pending_controls": operations["pending_controls"],
        "unresolved_controls": controls,
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
    acts = _objects(view.get("research_acts"))
    findings = _objects(view.get("findings"))
    return {
        **row,
        "workspace_id": workspace_id,
        "label": label,
        "source_root": source_root,
        "kernel_protocol": _object(view.get("workspace")).get("kernel_protocol"),
        "workspace_revision": view.get("workspace_revision"),
        "valid": bool(view.get("valid")),
        "claim_count": len(claims),
        "act_count": len(acts),
        "open_act_count": sum(1 for act in acts if act.get("status") == "open"),
        "open_finding_count": sum(1 for finding in findings if finding.get("status") == "open"),
        "focus_claim_refs": _strings(focus.get("claim_refs")),
        "focus_act_refs": _strings(focus.get("act_refs")),
        "acceptance_record_count": len(_objects(view.get("acceptances"))),
        "current_acceptance_count": len(_objects(view.get("current_acceptances"))),
    }


def graph_payload(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    return graph_payload_from_view(normalize_workspace(source_root, label=label))


def graph_payload_from_view(view: dict[str, Any]) -> dict[str, Any]:
    focus = _object(view.get("focus"))
    focus_claims = set(_strings(focus.get("claim_refs")))
    focus_acts = set(_strings(focus.get("act_refs")))
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
            "validation_spec_count": len(_strings(record.get("validation_spec_refs"))),
            "validation_result_count": len(_strings(record.get("validation_result_refs"))),
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
    acts = [
        {
            "id": record.get("act_id"),
            "act_id": record.get("act_id"),
            "objective": record.get("objective"),
            "status": record.get("status"),
            "tags": _strings(record.get("tags")),
            "claim_refs": _strings(record.get("claim_refs")),
            "dependency_refs": _strings(record.get("dependency_refs")),
            "focus": record.get("act_id") in focus_acts,
            "outcome": _object(record.get("result")).get("outcome"),
            "activity_count": len(_objects(record.get("activities"))),
            "review_count": len(_objects(record.get("review_runs"))),
            "unresolved_control_count": len(_objects(record.get("unresolved_controls"))),
        }
        for record in _objects(view.get("research_acts"))
    ]
    act_edges = [
        {
            "id": f"dependency:{dependency}:{act['act_id']}",
            "source": dependency,
            "target": act["act_id"],
            "kind": "depends_on",
        }
        for act in acts
        for dependency in act["dependency_refs"]
    ]
    claim_act_links = [
        {"claim_ref": claim_ref, "act_ref": act["act_id"]}
        for act in acts
        for claim_ref in act["claim_refs"]
    ]
    return {
        "schema_version": "ts-explorer-graph/4",
        "workspace": view.get("workspace"),
        "workspace_revision": view.get("workspace_revision"),
        "operational_revision": view.get("operational_revision"),
        "valid": bool(view.get("valid")),
        "validation_findings": _list(view.get("validation_findings")),
        "focus": focus,
        "claim_graph": {"nodes": claims, "edges": relations},
        "research_act_dag": {"nodes": acts, "edges": act_edges},
        "claim_act_links": claim_act_links,
        "semantic_summary": _semantic_summary(view),
        "operational_summary": _object(view.get("operational_summary")),
        "deterministic_activities": _objects(view.get("deterministic_activities")),
        "review_runs": _objects(view.get("review_runs")),
        "unresolved_controls": _objects(view.get("unresolved_controls")),
    }


def claim_payload(source_root: str | Path, claim_id: str, *, label: str | None = None) -> dict[str, Any]:
    view = normalize_workspace(source_root, label=label)
    claim = _find(_objects(view.get("claims")), "claim_id", claim_id, "Claim")
    relations = [
        row
        for row in _objects(view.get("claim_relations"))
        if claim_id in {row.get("source_claim_ref"), row.get("target_claim_ref")}
    ]
    acts = [row for row in _objects(view.get("research_acts")) if claim_id in _strings(row.get("claim_refs"))]
    act_ids = {str(row.get("act_id")) for row in acts}
    observation_ids = {
        *_strings(claim.get("observation_refs")),
        *(ref for act in acts for ref in _strings(act.get("observation_refs"))),
    }
    return {
        "schema_version": "ts-explorer-claim/1",
        "claim": claim,
        "relations": relations,
        "research_acts": acts,
        "observations": [
            row for row in _objects(view.get("observations")) if row.get("observation_id") in observation_ids
        ],
        "validation_specs": [
            row for row in _objects(view.get("validation_specs")) if row.get("target_claim_ref") == claim_id
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
            for row in _objects(view.get("review_runs"))
            if claim_id in _strings(row.get("claim_refs")) or act_ids.intersection(_strings(row.get("act_refs")))
        ],
    }


def act_payload(source_root: str | Path, act_id: str, *, label: str | None = None) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve()
    view = normalize_workspace(root, label=label)
    act = _find(_objects(view.get("research_acts")), "act_id", act_id, "ResearchAct")
    dependency_ids = set(_strings(act.get("dependency_refs")))
    all_acts = _objects(view.get("research_acts"))
    return {
        "schema_version": "ts-explorer-research-act/1",
        "research_act": act,
        "dependencies": [row for row in all_acts if row.get("act_id") in dependency_ids],
        "dependents": [row for row in all_acts if act_id in _strings(row.get("dependency_refs"))],
        "claims": [
            row for row in _objects(view.get("claims")) if row.get("claim_id") in _strings(act.get("claim_refs"))
        ],
        "observations": [
            row
            for row in _objects(view.get("observations"))
            if row.get("created_by_act") == act_id or row.get("observation_id") in _strings(act.get("observation_refs"))
        ],
        "validation_specs": [
            row
            for row in _objects(view.get("validation_specs"))
            if row.get("created_by_act") == act_id or row.get("spec_id") in _strings(act.get("validation_spec_refs"))
        ],
        "validation_results": [
            row
            for row in _objects(view.get("validation_results"))
            if row.get("evaluated_by_act") == act_id or row.get("result_id") in _strings(act.get("validation_result_refs"))
        ],
        "findings": [
            row for row in _objects(view.get("findings")) if act_id in _strings(row.get("act_refs"))
        ],
        "files": list_act_files(root, act_id),
    }


def list_act_files(source_root: str | Path, act_id: str) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve()
    act_dir = root / "acts" / act_id
    if not act_dir.is_dir() or act_dir.is_symlink():
        return {"act_id": act_id, "files": []}
    files: list[dict[str, Any]] = []
    for path in sorted(act_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "name": path.name,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            }
        )
    return {"act_id": act_id, "files": files}


def _normalize_act(
    root: Path,
    record: dict[str, Any],
    *,
    activities: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    controls: list[dict[str, Any]],
) -> dict[str, Any]:
    act_id = str(record.get("act_id") or "")
    return {
        **record,
        "attempts": _calculation_attempts(root, act_id),
        "activities": [row for row in activities if act_id in _strings(row.get("act_refs"))],
        "review_runs": [row for row in reviews if act_id in _strings(row.get("act_refs"))],
        "unresolved_controls": [row for row in controls if row.get("act_id") == act_id],
    }


def _calculation_attempts(root: Path, act_id: str) -> list[dict[str, Any]]:
    if not act_id:
        return []
    attempts: list[dict[str, Any]] = []
    for attempt_dir in sorted((root / "acts" / act_id / "attempts").glob("*")):
        if not attempt_dir.is_dir() or attempt_dir.is_symlink():
            continue
        result = _read_optional_object(attempt_dir / "outputs" / "calculation_result.json")
        status = _read_optional_object(attempt_dir / "status.json")
        intent = _read_optional_object(attempt_dir / "intent.json")
        attempts.append(
            {
                "intent_id": intent.get("intent_id") or status.get("intent_id") or attempt_dir.name,
                "ref": attempt_dir.relative_to(root).as_posix(),
                "backend": intent.get("backend") or result.get("backend"),
                "task_type": intent.get("task_type") or result.get("task_type"),
                "state": result.get("state") or status.get("state"),
                "program_status": result.get("program_status") or status.get("program_status"),
                "error_class": result.get("error_class") or status.get("error_class"),
            }
        )
    return attempts


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
    acts = _objects(view.get("research_acts"))
    results = _objects(view.get("validation_results"))
    findings = _objects(view.get("findings"))
    return {
        "claim_count": len(claims),
        "claim_statuses": _counts(claims, "status"),
        "act_count": len(acts),
        "act_statuses": _counts(acts, "status"),
        "observation_count": len(_objects(view.get("observations"))),
        "validation_spec_count": len(_objects(view.get("validation_specs"))),
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


def _find(records: list[dict[str, Any]], key: str, value: str, label: str) -> dict[str, Any]:
    record = next((row for row in records if row.get(key) == value), None)
    if record is None:
        raise ValueError(f"unknown {label}: {value}")
    return record


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read v4 workspace file {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"v4 workspace file is not an object: {path.name}")
    return value


def _read_optional_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
