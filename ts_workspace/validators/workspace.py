"""Workspace contract validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_policy import consumed_paths_from_manifest, node_owner_from_artifact_path, role_matches_phase
from ..evidence_gates import (
    STEREOCHEMICAL_GATE_ROLE,
    accepted_gate_evidence,
    hypothesis_requires_stereochemical_gate,
    stereochemical_gate_diagnostic,
    strict_connectivity_diagnostic,
)
from ..io import read_json
from ..schema_validation import schema_findings
from .decision import (
    FORBIDDEN_PUBLIC_FIELDS,
    HYPOTHESIS_REF_PHASES,
    INITIAL_HYPOTHESIS_PHASES,
    VALID_CLAIM_VERDICTS,
    VALID_LIFECYCLES,
    VALID_PHASES,
    VALID_PROGRAM_STATUSES,
)

REQUIRED_FILES = {
    "manifest.json",
    "tree.json",
    "evidence_registry.json",
    "mechanism_model.json",
    "pathway_model.json",
    "knowledge_base.md",
}

REQUIRED_DIRS = {"inputs", "nodes", "reports", "accepted", "rejected"}
UNRESOLVED_TERMINAL_VERDICTS = {"refuted", "inconclusive", "not_evaluated"}
SCHEMA_BY_FILE = {
    "manifest.json": "manifest.schema.json",
    "tree.json": "tree.schema.json",
    "evidence_registry.json": "evidence_registry.schema.json",
    "mechanism_model.json": "mechanism.schema.json",
    "pathway_model.json": "pathway.schema.json",
}


def validate_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    findings: list[dict[str, str]] = []

    for filename in sorted(REQUIRED_FILES):
        path = root_path / filename
        if not path.exists():
            _finding(findings, "error", "missing_file", f"missing {filename}", filename)

    for dirname in sorted(REQUIRED_DIRS):
        path = root_path / dirname
        if not path.is_dir():
            _finding(findings, "error", "missing_dir", f"missing {dirname}/", dirname)

    loaded: dict[str, Any] = {}
    for filename in sorted(REQUIRED_FILES - {"knowledge_base.md"}):
        path = root_path / filename
        if path.exists():
            try:
                loaded[filename] = read_json(path)
            except Exception as exc:  # noqa: BLE001
                _finding(findings, "error", "invalid_json", str(exc), filename)
                continue
            schema_name = SCHEMA_BY_FILE.get(filename)
            if schema_name:
                findings.extend(schema_findings(schema_name, loaded[filename], filename))

    mechanism_model = loaded.get("mechanism_model.json", {})
    hypothesis_ids = _validate_mechanism_model(mechanism_model, findings)
    tree = loaded.get("tree.json", {})
    node_entries = tree.get("nodes", []) if isinstance(tree, dict) else []
    node_ids = set()
    node_details: dict[str, dict[str, Any]] = {}
    ordered_node_ids: list[str] = []
    if not isinstance(node_entries, list):
        _finding(findings, "error", "invalid_tree", "tree.nodes must be a list", "tree.json")
        node_entries = []

    for entry in node_entries:
        if not isinstance(entry, dict):
            _finding(findings, "error", "invalid_tree_node", "tree node entry must be an object", "tree.json")
            continue
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            _finding(findings, "error", "invalid_node_id", "tree node missing node_id", "tree.json")
            continue
        node_ids.add(node_id)
        ordered_node_ids.append(node_id)
        node_path = root_path / "nodes" / node_id / "node.json"
        if not node_path.exists():
            _finding(findings, "error", "missing_node_json", f"missing node.json for {node_id}", str(node_path))
            continue
        try:
            node = read_json(node_path)
        except Exception as exc:  # noqa: BLE001
            _finding(findings, "error", "invalid_node_json", str(exc), str(node_path))
            continue
        findings.extend(schema_findings("node.schema.json", node, str(node_path)))
        if not isinstance(node, dict):
            _finding(findings, "error", "invalid_node_json", "node.json must contain an object", str(node_path))
            continue
        node_details[node_id] = node
        _validate_node(node, node_id, hypothesis_ids, findings, str(node_path))

    current_node = tree.get("current_node") if isinstance(tree, dict) else None
    if current_node is not None and current_node not in node_ids:
        _finding(findings, "error", "invalid_current_node", "tree.current_node does not exist", "tree.json")
    if isinstance(tree, dict):
        _validate_initial_node_sequence(ordered_node_ids, node_details, hypothesis_ids, findings)
        _validate_backtrack_events(tree, node_ids, findings)
        _validate_replacement_backtrack_sequence(tree, ordered_node_ids, node_details, findings)
        _validate_unresolved_terminal_state(
            tree,
            _as_dict(loaded.get("manifest.json")),
            _as_dict(loaded.get("pathway_model.json")),
            ordered_node_ids,
            node_details,
            findings,
        )

    for filename, data in loaded.items():
        _reject_forbidden(data, findings, filename)

    evidence = _as_dict(loaded.get("evidence_registry.json")).get("evidence", [])
    evidence_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(evidence, list):
        ids: set[str] = set()
        for item in evidence:
            if not isinstance(item, dict):
                _finding(findings, "error", "invalid_evidence", "evidence entry must be an object", "evidence_registry.json")
                continue
            evidence_id = item.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                _finding(findings, "error", "invalid_evidence_id", "evidence entry missing evidence_id", "evidence_registry.json")
            elif evidence_id in ids:
                _finding(findings, "error", "duplicate_evidence_id", f"duplicate evidence {evidence_id}", "evidence_registry.json")
            else:
                ids.add(evidence_id)
                evidence_by_id[evidence_id] = item
            quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
            hypothesis_id = quality.get("hypothesis_id")
            if hypothesis_id is not None and hypothesis_id not in hypothesis_ids:
                _finding(
                    findings,
                    "error",
                    "unknown_evidence_hypothesis",
                    f"evidence references unknown hypothesis_id: {hypothesis_id}",
                    "evidence_registry.json",
                )
        _validate_evidence_artifact_boundaries(root_path, evidence, node_details, findings)

    _validate_accepted_ts_refs(
        root_path,
        _as_dict(loaded.get("manifest.json")),
        _as_dict(loaded.get("mechanism_model.json")),
        evidence_by_id,
        findings,
    )

    return {"valid": not any(item["severity"] == "error" for item in findings), "findings": findings}


def _validate_node(
    node: dict[str, Any],
    expected_id: str,
    hypothesis_ids: set[str],
    findings: list[dict[str, str]],
    source: str,
) -> None:
    if node.get("node_id") != expected_id:
        _finding(findings, "error", "node_id_mismatch", "node_id does not match tree entry", source)
    if node.get("phase") not in VALID_PHASES:
        _finding(findings, "error", "invalid_phase", "node phase is invalid", source)
    lifecycle = node.get("lifecycle")
    if lifecycle not in VALID_LIFECYCLES:
        _finding(findings, "error", "invalid_lifecycle", "node lifecycle is invalid", source)
    if not isinstance(node.get("hypothesis"), str) or not node["hypothesis"].strip():
        _finding(findings, "error", "missing_hypothesis", "node hypothesis is required", source)
    phase = node.get("phase")
    if phase in INITIAL_HYPOTHESIS_PHASES and not isinstance(node.get("initial_mechanism_hypothesis"), dict):
        _finding(
            findings,
            "error",
            "missing_initial_mechanism_hypothesis",
            "endpoint/preflight node requires initial_mechanism_hypothesis",
            source,
        )
    if phase in HYPOTHESIS_REF_PHASES:
        _validate_hypothesis_ref(node.get("hypothesis_ref"), hypothesis_ids, findings, source, "node.hypothesis_ref")

    closure = node.get("closure")
    if lifecycle == "running" and closure is not None:
        _finding(findings, "error", "running_node_has_closure", "running node cannot have closure", source)
    if lifecycle in {"closed", "stopped"}:
        if not isinstance(closure, dict):
            _finding(findings, "error", "missing_closure", "closed or stopped node requires closure", source)
            return
        if closure.get("program_status") not in VALID_PROGRAM_STATUSES:
            _finding(findings, "error", "invalid_program_status", "closure.program_status is invalid", source)
        if closure.get("claim_verdict") not in VALID_CLAIM_VERDICTS:
            _finding(findings, "error", "invalid_claim_verdict", "closure.claim_verdict is invalid", source)
        mechanism = closure.get("mechanism") if isinstance(closure.get("mechanism"), dict) else {}
        if phase in HYPOTHESIS_REF_PHASES:
            _validate_hypothesis_ref(
                mechanism.get("hypothesis_ref"),
                hypothesis_ids,
                findings,
                source,
                "closure.mechanism.hypothesis_ref",
            )
            node_ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
            mech_ref = mechanism.get("hypothesis_ref") if isinstance(mechanism.get("hypothesis_ref"), dict) else {}
            if node_ref.get("hypothesis_id") != mech_ref.get("hypothesis_id"):
                _finding(
                    findings,
                    "error",
                    "mismatched_closure_hypothesis_ref",
                    "closure mechanism hypothesis_ref must match node hypothesis_ref",
                    source,
                )


def _validate_mechanism_model(model: Any, findings: list[dict[str, str]]) -> set[str]:
    source = "mechanism_model.json"
    hypothesis_ids: set[str] = set()
    if not isinstance(model, dict):
        _finding(findings, "error", "invalid_mechanism_model", "mechanism_model must be an object", source)
        return hypothesis_ids
    if model.get("schema_version") != "ts-mechanism":
        _finding(findings, "error", "invalid_mechanism_schema", "mechanism_model schema_version must be ts-mechanism", source)
    if "focus_hypothesis_id" not in model:
        _finding(findings, "error", "missing_focus_hypothesis_id", "mechanism_model.focus_hypothesis_id is required", source)
    hypotheses = model.get("hypotheses")
    if not isinstance(hypotheses, list):
        _finding(findings, "error", "invalid_hypotheses", "mechanism_model.hypotheses must be a list", source)
        return hypothesis_ids
    for index, hypothesis in enumerate(hypotheses):
        path = f"{source}.hypotheses[{index}]"
        if not isinstance(hypothesis, dict):
            _finding(findings, "error", "invalid_hypothesis", "hypothesis must be an object", path)
            continue
        hypothesis_id = hypothesis.get("hypothesis_id")
        if not isinstance(hypothesis_id, str) or not hypothesis_id:
            _finding(findings, "error", "missing_hypothesis_id", "hypothesis_id is required", path)
            continue
        if hypothesis_id in hypothesis_ids:
            _finding(findings, "error", "duplicate_hypothesis_id", f"duplicate hypothesis_id: {hypothesis_id}", path)
        hypothesis_ids.add(hypothesis_id)
        for field in ("summary", "status", "source_node"):
            if not isinstance(hypothesis.get(field), str) or not hypothesis[field].strip():
                _finding(findings, "error", "invalid_hypothesis", f"{field} is required", path)
        if not isinstance(hypothesis.get("structured_claim"), dict):
            _finding(findings, "error", "invalid_hypothesis", "structured_claim must be an object", path)
        if not isinstance(hypothesis.get("testable_predictions"), list):
            _finding(findings, "error", "invalid_hypothesis", "testable_predictions must be a list", path)
        if not isinstance(hypothesis.get("required_evidence"), list):
            _finding(findings, "error", "invalid_hypothesis", "required_evidence must be a list", path)
    focus = model.get("focus_hypothesis_id")
    if focus is not None and focus not in hypothesis_ids:
        _finding(findings, "error", "invalid_focus_hypothesis_id", "focus_hypothesis_id does not exist", source)
    return hypothesis_ids


def _validate_hypothesis_ref(
    value: Any,
    hypothesis_ids: set[str],
    findings: list[dict[str, str]],
    source: str,
    label: str,
) -> None:
    if not isinstance(value, dict):
        _finding(findings, "error", "missing_hypothesis_ref", f"{label} is required", source)
        return
    hypothesis_id = value.get("hypothesis_id")
    if not isinstance(hypothesis_id, str) or not hypothesis_id:
        _finding(findings, "error", "invalid_hypothesis_ref", f"{label}.hypothesis_id is required", source)
    elif hypothesis_id not in hypothesis_ids:
        _finding(findings, "error", "unknown_hypothesis_ref", f"{label} references unknown hypothesis_id: {hypothesis_id}", source)
    prediction_ids = value.get("prediction_ids", [])
    if not isinstance(prediction_ids, list):
        _finding(findings, "error", "invalid_hypothesis_ref", f"{label}.prediction_ids must be a list", source)


def _validate_backtrack_events(tree: dict[str, Any], node_ids: set[str], findings: list[dict[str, str]]) -> None:
    events = tree.get("backtrack_events", [])
    if not isinstance(events, list):
        _finding(findings, "error", "invalid_backtrack_events", "tree.backtrack_events must be a list", "tree.json")
        return
    for index, event in enumerate(events):
        path = f"tree.json.backtrack_events[{index}]"
        if not isinstance(event, dict):
            _finding(findings, "error", "invalid_backtrack_event", "backtrack event must be an object", path)
            continue
        for field in ("from_node", "to_node", "new_branch_node"):
            node_id = event.get(field)
            if not isinstance(node_id, str) or not node_id:
                _finding(findings, "error", "invalid_backtrack_event", f"{field} is required", path)
            elif node_id not in node_ids:
                _finding(findings, "error", "invalid_backtrack_event_node", f"{field} does not exist: {node_id}", path)


def _validate_initial_node_sequence(
    ordered_node_ids: list[str],
    node_details: dict[str, dict[str, Any]],
    hypothesis_ids: set[str],
    findings: list[dict[str, str]],
) -> None:
    if not ordered_node_ids:
        return
    first_id = ordered_node_ids[0]
    first = node_details.get(first_id, {})
    if first_id != "n000":
        _finding(findings, "error", "missing_n000", "first node must be n000", "tree.json.nodes[0]")
    if first.get("phase") not in INITIAL_HYPOTHESIS_PHASES:
        _finding(findings, "error", "invalid_n000_phase", "n000 must be endpoint or preflight", "nodes/n000/node.json")
    closure = first.get("closure")
    if isinstance(closure, dict) and closure.get("program_status") == "completed" and closure.get("claim_verdict") == "supported":
        if not hypothesis_ids:
            _finding(
                findings,
                "error",
                "missing_finalized_hypothesis",
                "supported n000 must finalize at least one mechanism hypothesis",
                "mechanism_model.json.hypotheses",
            )


def _validate_replacement_backtrack_sequence(
    tree: dict[str, Any],
    ordered_node_ids: list[str],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    """Require explicit provenance when a failed terminal node is replaced."""

    events = _backtrack_events(tree)
    parent_by_id = {node_id: node.get("parent_node") for node_id, node in node_details.items()}
    for index, node_id in enumerate(ordered_node_ids[1:], start=1):
        previous_id = ordered_node_ids[index - 1]
        previous = node_details.get(previous_id, {})
        current = node_details.get(node_id, {})
        if not _is_unresolved_closed(previous):
            continue
        if _is_descendant(node_id, previous_id, parent_by_id):
            continue
        if _has_replacement_event(events, previous_id, node_id):
            continue
        verdict = _claim_verdict(previous)
        _finding(
            findings,
            "error",
            "missing_replacement_backtrack_event",
            (
                f"node {node_id} starts after terminal {verdict} node {previous_id} "
                "without a canonical backtrack event"
            ),
            "tree.json.backtrack_events",
        )


def _validate_unresolved_terminal_state(
    tree: dict[str, Any],
    manifest: dict[str, Any],
    pathway_model: dict[str, Any],
    ordered_node_ids: list[str],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    if tree.get("current_node") or any(node.get("lifecycle") == "running" for node in node_details.values()):
        return
    if _has_accepted_claim(manifest, pathway_model):
        return
    if not ordered_node_ids:
        return
    terminal_id = ordered_node_ids[-1]
    terminal = node_details.get(terminal_id, {})
    if not _is_unresolved_closed(terminal):
        return
    verdict = _claim_verdict(terminal)
    _finding(
        findings,
        "error",
        "workspace_needs_followup",
        (
            f"terminal node {terminal_id} is {verdict} and the workspace has no "
            "running node or accepted TS/pathway"
        ),
        "tree.json.current_node",
    )


def _backtrack_events(tree: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in tree.get("backtrack_events", []) if isinstance(event, dict)]


def _has_replacement_event(events: list[dict[str, Any]], from_node: str, new_branch_node: str) -> bool:
    return any(
        event.get("from_node") == from_node and event.get("new_branch_node") == new_branch_node
        for event in events
    )


def _is_unresolved_closed(node: dict[str, Any]) -> bool:
    return node.get("lifecycle") in {"closed", "stopped"} and _claim_verdict(node) in UNRESOLVED_TERMINAL_VERDICTS


def _claim_verdict(node: dict[str, Any]) -> str | None:
    closure = node.get("closure")
    if isinstance(closure, dict):
        return closure.get("claim_verdict")
    return node.get("claim_verdict")


def _is_descendant(node_id: str, ancestor_id: str, parent_by_id: dict[str, Any]) -> bool:
    current = parent_by_id.get(node_id)
    seen: set[str] = set()
    while isinstance(current, str) and current and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        current = parent_by_id.get(current)
    return False


def _has_accepted_claim(manifest: dict[str, Any], pathway_model: dict[str, Any]) -> bool:
    if _as_list(manifest.get("accepted_ts_refs")):
        return True
    for pathway in _as_list(pathway_model.get("pathways")):
        if isinstance(pathway, dict) and pathway.get("status") == "accepted":
            return True
    return False


def _validate_accepted_ts_refs(
    root: Path,
    manifest: dict[str, Any],
    mechanism_model: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    for ref in _as_list(manifest.get("accepted_ts_refs")):
        if not isinstance(ref, str) or not ref:
            _finding(findings, "error", "invalid_accepted_ts_ref", "accepted_ts_ref must be a non-empty string", "manifest.json")
            continue
        path = root / ref
        if not path.exists():
            _finding(findings, "error", "missing_accepted_ts_artifact", f"missing accepted artifact: {ref}", ref)
            continue
        try:
            artifact = read_json(path)
        except Exception as exc:  # noqa: BLE001
            _finding(findings, "error", "invalid_accepted_ts_artifact", str(exc), ref)
            continue
        findings.extend(schema_findings("accepted_ts.schema.json", artifact, ref))
        if not isinstance(artifact, dict):
            _finding(findings, "error", "invalid_accepted_ts_artifact", "accepted artifact must be an object", ref)
            continue
        evidence_refs = [str(item) for item in _as_list(artifact.get("evidence_refs")) if item]
        hypothesis_id = _artifact_hypothesis_id(artifact)
        hypothesis = _mechanism_hypothesis_by_id(mechanism_model, hypothesis_id)
        require_stereo = hypothesis_requires_stereochemical_gate(hypothesis)
        try:
            gate_evidence = accepted_gate_evidence(
                list(evidence_by_id.values()),
                evidence_refs,
                require_stereochemical_gate=require_stereo,
            )
        except ValueError as exc:
            _finding(findings, "error", "invalid_accepted_ts_gates", str(exc), ref)
            continue
        if hypothesis_id and gate_evidence.get("__hypothesis_id") != hypothesis_id:
            _finding(
                findings,
                "error",
                "invalid_accepted_ts_hypothesis",
                "accepted artifact gate evidence must match artifact.hypothesis_ref",
                ref,
            )
        diagnostic = strict_connectivity_diagnostic(gate_evidence["connectivity_gate"])
        if diagnostic:
            _finding(findings, "error", "non_strict_accepted_ts_connectivity", diagnostic, ref)
        if require_stereo:
            stereo_diagnostic = stereochemical_gate_diagnostic(gate_evidence[STEREOCHEMICAL_GATE_ROLE])
            if stereo_diagnostic:
                _finding(findings, "error", "invalid_accepted_ts_stereochemistry", stereo_diagnostic, ref)


def _artifact_hypothesis_id(artifact: dict[str, Any]) -> str | None:
    hypothesis_ref = artifact.get("hypothesis_ref")
    if not isinstance(hypothesis_ref, dict):
        return None
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    return str(hypothesis_id) if hypothesis_id else None


def _mechanism_hypothesis_by_id(model: dict[str, Any], hypothesis_id: str | None) -> dict[str, Any] | None:
    if not hypothesis_id:
        return None
    for item in model.get("hypotheses", []):
        if isinstance(item, dict) and item.get("hypothesis_id") == hypothesis_id:
            return item
    return None


def _validate_evidence_artifact_boundaries(
    root: Path,
    evidence: list[Any],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    manifest_cache: dict[str, dict[str, Any] | None] = {}
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        source = f"evidence_registry.json.evidence[{index}]"
        evidence_id = str(item.get("evidence_id") or f"#{index}")
        node_id = item.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        node = node_details.get(node_id)
        if node is None:
            _finding(findings, "error", "unknown_evidence_node", f"evidence {evidence_id} references unknown node {node_id}", source)
            continue
        phase = node.get("phase")
        if not role_matches_phase(item.get("role"), phase):
            _finding(
                findings,
                "warning",
                "evidence_role_phase_mismatch",
                f"evidence {evidence_id} role {item.get('role')!r} is not owned by node phase {phase!r}",
                source,
            )
        path = item.get("path")
        owner = node_owner_from_artifact_path(path)
        if owner is None or owner == node_id:
            continue
        _finding(
            findings,
            "warning",
            "cross_node_evidence_path",
            f"evidence {evidence_id} belongs to {node_id} but path points into node {owner}",
            source,
        )
        manifest = _artifact_manifest(root, node_id, manifest_cache, findings)
        consumed = consumed_paths_from_manifest(manifest)
        if isinstance(path, str) and path not in consumed:
            _finding(
                findings,
                "warning",
                "missing_artifact_manifest_consumed_path",
                f"node {node_id} should declare consumed artifact {path!r} in outputs/artifact_manifest.json",
                f"nodes/{node_id}/outputs/artifact_manifest.json",
            )


def _artifact_manifest(
    root: Path,
    node_id: str,
    cache: dict[str, dict[str, Any] | None],
    findings: list[dict[str, str]],
) -> dict[str, Any] | None:
    if node_id in cache:
        return cache[node_id]
    path = root / "nodes" / node_id / "outputs" / "artifact_manifest.json"
    if not path.exists():
        cache[node_id] = None
        return None
    try:
        manifest = read_json(path)
    except Exception as exc:  # noqa: BLE001
        _finding(findings, "error", "invalid_artifact_manifest", str(exc), str(path))
        cache[node_id] = None
        return None
    findings.extend(schema_findings("artifact_manifest.schema.json", manifest, str(path)))
    node = read_json(root / "nodes" / node_id / "node.json")
    if isinstance(manifest, dict):
        if manifest.get("node_id") != node_id:
            _finding(findings, "error", "artifact_manifest_node_mismatch", "artifact manifest node_id must match node", str(path))
        if manifest.get("phase") != node.get("phase"):
            _finding(findings, "error", "artifact_manifest_phase_mismatch", "artifact manifest phase must match node phase", str(path))
    cache[node_id] = manifest if isinstance(manifest, dict) else None
    return cache[node_id]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _reject_forbidden(value: Any, findings: list[dict[str, str]], path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_PUBLIC_FIELDS:
                _finding(findings, "error", "forbidden_public_field", f"forbidden field {key}", path)
            _reject_forbidden(nested, findings, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden(nested, findings, f"{path}[{index}]")


def _finding(findings: list[dict[str, str]], severity: str, code: str, message: str, path: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message, "path": path})
