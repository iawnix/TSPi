"""Cross-document validation for the v4 research Kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_validation import builtin_predicate_registry, evaluate_gate_spec, load_acceptance_profile
from ts_validation.digests import sha256_json

from .acceptance import AcceptanceError, acceptance_currentness, acceptance_path, acceptance_policy_violations
from .identity import WorkspaceIdentityError, read_workspace_identity
from .io import read_json
from .refs import WorkspaceRefError, validate_artifact_bindings
from .schema_validation import schema_findings
from .state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    LEGACY_MARKERS,
    RESEARCH_ACTS_FILE,
    RESEARCH_STATE_FILE,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    STATE_FILES,
    STATE_SCHEMAS,
    VALIDATION_RESULTS_FILE,
    VALIDATION_SPECS_FILE,
    WORKSPACE_FILE,
)


def validate_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    findings: list[dict[str, str]] = []
    if root_path.is_symlink():
        _finding(findings, "error", "symlinked_workspace", "workspace root cannot be a symbolic link", ".")
        return _result(findings)
    if not root_path.is_dir():
        _finding(findings, "error", "missing_workspace", "workspace root does not exist", ".")
        return _result(findings)

    for marker in sorted(LEGACY_MARKERS):
        if (root_path / marker).exists():
            _finding(
                findings,
                "error",
                "legacy_state_present",
                f"legacy canonical state is unsupported by v4: {marker}",
                marker,
            )
    for name in sorted(REQUIRED_FILES):
        path = root_path / name
        if not path.is_file() or path.is_symlink():
            _finding(findings, "error", "missing_required_file", f"required file is missing: {name}", name)
    for name in sorted(REQUIRED_DIRS):
        path = root_path / name
        if not path.is_dir() or path.is_symlink():
            _finding(findings, "error", "missing_required_directory", f"required directory is missing: {name}", name)
    if findings:
        return _result(findings)

    documents: dict[str, dict[str, Any]] = {}
    for name in STATE_FILES:
        try:
            value = read_json(root_path / name)
        except (OSError, ValueError) as exc:
            _finding(findings, "error", "invalid_json", str(exc), name)
            continue
        if not isinstance(value, dict):
            _finding(findings, "error", "invalid_document", "canonical state must be an object", name)
            continue
        documents[name] = value
        findings.extend(schema_findings(STATE_SCHEMAS[name], value, name))
    if len(documents) != len(STATE_FILES) or findings:
        return _result(findings)

    try:
        identity = read_workspace_identity(root_path)
        if documents[WORKSPACE_FILE].get("workspace_id") != identity.get("workspace_id"):
            _finding(findings, "error", "workspace_identity_mismatch", "workspace.json does not match immutable identity", WORKSPACE_FILE)
    except WorkspaceIdentityError as exc:
        _finding(findings, "error", "invalid_workspace_identity", str(exc), ".agents/workspace-identity.json")

    claims = _unique_map(documents[CLAIMS_FILE].get("claims"), "claim_id", CLAIMS_FILE, findings)
    relations = _unique_map(documents[CLAIM_RELATIONS_FILE].get("relations"), "relation_id", CLAIM_RELATIONS_FILE, findings)
    acts = _unique_map(documents[RESEARCH_ACTS_FILE].get("acts"), "act_id", RESEARCH_ACTS_FILE, findings)
    observations = _unique_map(documents[OBSERVATIONS_FILE].get("observations"), "observation_id", OBSERVATIONS_FILE, findings)
    specs = _unique_map(documents[VALIDATION_SPECS_FILE].get("specs"), "spec_id", VALIDATION_SPECS_FILE, findings)
    results = _unique_map(documents[VALIDATION_RESULTS_FILE].get("results"), "result_id", VALIDATION_RESULTS_FILE, findings)
    finding_map = _unique_map(documents[FINDINGS_FILE].get("findings"), "finding_id", FINDINGS_FILE, findings)

    _require_refs(documents[RESEARCH_STATE_FILE].get("focus_claim_refs"), claims, "focus_claim_refs", RESEARCH_STATE_FILE, findings)
    _require_refs(documents[RESEARCH_STATE_FILE].get("focus_act_refs"), acts, "focus_act_refs", RESEARCH_STATE_FILE, findings)
    _validate_claims(claims, acts, observations, specs, results, findings)
    _validate_claim_relations(relations, claims, findings)
    _validate_acts(acts, claims, observations, specs, results, finding_map, findings)
    _validate_observations(observations, acts, findings)
    _validate_findings(finding_map, claims, acts, observations, findings)
    _validate_specs_and_results(specs, results, claims, acts, observations, findings)
    _validate_acceptance(root_path, documents, claims, specs, results, finding_map, findings)
    return _result(findings)


def _validate_claims(
    claims: dict[str, dict[str, Any]],
    acts: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    for claim_id, claim in claims.items():
        act_ref = claim.get("created_by_act")
        if act_ref is not None and act_ref not in acts:
            _finding(findings, "error", "unknown_claim_creator", f"Claim {claim_id} references unknown creator Act", CLAIMS_FILE)
        _require_refs(claim.get("observation_refs"), observations, f"Claim {claim_id} observation_refs", CLAIMS_FILE, findings)
        _require_refs(claim.get("validation_spec_refs"), specs, f"Claim {claim_id} validation_spec_refs", CLAIMS_FILE, findings)
        _require_refs(claim.get("validation_result_refs"), results, f"Claim {claim_id} validation_result_refs", CLAIMS_FILE, findings)
        for history in claim.get("history", []):
            if not isinstance(history, dict):
                continue
            _require_refs(history.get("observation_refs"), observations, f"Claim {claim_id} history observations", CLAIMS_FILE, findings)
            _require_refs(history.get("validation_result_refs"), results, f"Claim {claim_id} history results", CLAIMS_FILE, findings)


def _validate_claim_relations(
    relations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    edges: list[tuple[str, str]] = []
    for relation_id, relation in relations.items():
        source = str(relation.get("source_claim_ref") or "")
        target = str(relation.get("target_claim_ref") or "")
        if source not in claims or target not in claims:
            _finding(findings, "error", "unknown_claim_relation_ref", f"Claim relation {relation_id} has an unknown endpoint", CLAIM_RELATIONS_FILE)
        elif source == target:
            _finding(findings, "error", "claim_relation_self_edge", f"Claim relation {relation_id} is a self edge", CLAIM_RELATIONS_FILE)
        else:
            edges.append((source, target))
    cycle = _find_cycle(set(claims), edges)
    if cycle:
        _finding(findings, "error", "claim_graph_cycle", "Claim relation DAG contains a cycle: " + " -> ".join(cycle), CLAIM_RELATIONS_FILE)


def _validate_acts(
    acts: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    finding_map: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    edges: list[tuple[str, str]] = []
    for act_id, act in acts.items():
        if act.get("artifact_root") != f"acts/{act_id}":
            _finding(findings, "error", "act_artifact_root_mismatch", f"ResearchAct {act_id} has a non-canonical artifact root", RESEARCH_ACTS_FILE)
        dependencies = act.get("dependency_refs", [])
        _require_refs(dependencies, acts, f"ResearchAct {act_id} dependency_refs", RESEARCH_ACTS_FILE, findings)
        edges.extend((str(ref), act_id) for ref in dependencies if ref in acts)
        _require_refs(act.get("claim_refs"), claims, f"ResearchAct {act_id} claim_refs", RESEARCH_ACTS_FILE, findings)
        _require_refs(act.get("observation_refs"), observations, f"ResearchAct {act_id} observation_refs", RESEARCH_ACTS_FILE, findings)
        _require_refs(act.get("finding_refs"), finding_map, f"ResearchAct {act_id} finding_refs", RESEARCH_ACTS_FILE, findings)
        _require_refs(act.get("validation_spec_refs"), specs, f"ResearchAct {act_id} validation_spec_refs", RESEARCH_ACTS_FILE, findings)
        _require_refs(act.get("validation_result_refs"), results, f"ResearchAct {act_id} validation_result_refs", RESEARCH_ACTS_FILE, findings)
        state = act.get("status")
        if (state == "open") != (act.get("result") is None):
            _finding(findings, "error", "act_terminal_state_mismatch", f"ResearchAct {act_id} status/result are inconsistent", RESEARCH_ACTS_FILE)
    cycle = _find_cycle(set(acts), edges)
    if cycle:
        _finding(findings, "error", "research_act_cycle", "ResearchAct DAG contains a cycle: " + " -> ".join(cycle), RESEARCH_ACTS_FILE)


def _validate_observations(
    observations: dict[str, dict[str, Any]],
    acts: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    for observation_id, observation in observations.items():
        act_ref = observation.get("created_by_act")
        if act_ref not in acts:
            _finding(findings, "error", "unknown_observation_creator", f"Observation {observation_id} references unknown Act", OBSERVATIONS_FILE)
        elif observation_id not in acts[act_ref].get("observation_refs", []):
            _finding(findings, "error", "observation_owner_index_mismatch", f"Observation {observation_id} is not indexed by its creator Act", OBSERVATIONS_FILE)
        try:
            validate_artifact_bindings(observation)
        except WorkspaceRefError as exc:
            _finding(findings, "error", "invalid_observation_artifacts", f"Observation {observation_id}: {exc}", OBSERVATIONS_FILE)
        if not _datatype_matches(observation.get("datatype"), observation.get("value")):
            _finding(findings, "error", "observation_datatype_mismatch", f"Observation {observation_id} value does not match datatype", OBSERVATIONS_FILE)


def _validate_findings(
    finding_map: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    acts: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    for finding_id, record in finding_map.items():
        _require_refs(record.get("claim_refs"), claims, f"Finding {finding_id} claim_refs", FINDINGS_FILE, findings)
        _require_refs(record.get("act_refs"), acts, f"Finding {finding_id} act_refs", FINDINGS_FILE, findings)
        _require_refs(record.get("basis_observation_refs"), observations, f"Finding {finding_id} observations", FINDINGS_FILE, findings)
        for act_ref in record.get("act_refs", []):
            if act_ref in acts and finding_id not in acts[act_ref].get("finding_refs", []):
                _finding(findings, "error", "finding_owner_index_mismatch", f"Finding {finding_id} is not indexed by Act {act_ref}", FINDINGS_FILE)
        resolution = record.get("resolution")
        if (record.get("status") == "open") != (resolution is None):
            _finding(findings, "error", "finding_resolution_mismatch", f"Finding {finding_id} status/resolution are inconsistent", FINDINGS_FILE)
        if isinstance(resolution, dict):
            _require_refs(resolution.get("basis_observation_refs"), observations, f"Finding {finding_id} resolution observations", FINDINGS_FILE, findings)


def _validate_specs_and_results(
    specs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    acts: dict[str, dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    registry = builtin_predicate_registry()
    for spec_id, spec in specs.items():
        target = spec.get("target_claim_ref")
        creator = spec.get("created_by_act")
        if target not in claims or creator not in acts:
            _finding(findings, "error", "unknown_validation_spec_ref", f"GateSpec {spec_id} has an unknown target or creator", VALIDATION_SPECS_FILE)
            continue
        if spec_id not in claims[target].get("validation_spec_refs", []) or spec_id not in acts[creator].get("validation_spec_refs", []):
            _finding(findings, "error", "validation_spec_index_mismatch", f"GateSpec {spec_id} is missing from target indexes", VALIDATION_SPECS_FILE)
        expected = dict(spec)
        digest = expected.pop("spec_digest", None)
        if digest != sha256_json(expected):
            _finding(findings, "error", "validation_spec_digest_mismatch", f"GateSpec {spec_id} digest differs from content", VALIDATION_SPECS_FILE)
        if spec.get("predicate_registry_digest") != registry.digest:
            _finding(findings, "error", "validation_registry_mismatch", f"GateSpec {spec_id} uses a different predicate registry", VALIDATION_SPECS_FILE)

    for result_id, result in results.items():
        spec = specs.get(str(result.get("spec_ref") or ""))
        creator = acts.get(str(result.get("evaluated_by_act") or ""))
        target = claims.get(str(result.get("target_claim_ref") or ""))
        selected = [observations[ref] for ref in result.get("observation_refs", []) if ref in observations]
        if spec is None or creator is None or target is None or len(selected) != len(result.get("observation_refs", [])):
            _finding(findings, "error", "unknown_validation_result_ref", f"ValidationResult {result_id} has unknown inputs", VALIDATION_RESULTS_FILE)
            continue
        if result_id not in creator.get("validation_result_refs", []) or result_id not in target.get("validation_result_refs", []):
            _finding(findings, "error", "validation_result_index_mismatch", f"ValidationResult {result_id} is missing from target indexes", VALIDATION_RESULTS_FILE)
        try:
            expected = evaluate_gate_spec(
                spec,
                selected,
                result_id=result_id,
                evaluated_by_act=result["evaluated_by_act"],
                evaluated_by_decision=result["evaluated_by_decision"],
                registry=registry,
                evaluated_at=result["evaluated_at"],
            )
        except Exception as exc:
            _finding(findings, "error", "validation_result_recompute_error", f"ValidationResult {result_id} cannot be recomputed: {exc}", VALIDATION_RESULTS_FILE)
            continue
        if expected != result:
            _finding(findings, "error", "validation_result_mismatch", f"ValidationResult {result_id} differs from deterministic evaluation", VALIDATION_RESULTS_FILE)


def _validate_acceptance(
    root: Path,
    documents: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    finding_map: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    refs = documents[RESEARCH_STATE_FILE].get("acceptance_refs", [])
    acceptance_files = {
        path.relative_to(root).as_posix()
        for path in (root / "acceptances").glob("acc_*.json")
        if path.is_file() and not path.is_symlink()
    }
    if set(refs) != acceptance_files:
        _finding(findings, "error", "acceptance_index_mismatch", "research_state acceptance_refs does not match acceptance artifacts", RESEARCH_STATE_FILE)
    for ref in refs:
        try:
            path = acceptance_path(root, ref)
            record = read_json(path)
        except (AcceptanceError, OSError, ValueError) as exc:
            _finding(findings, "error", "invalid_acceptance", str(exc), ref)
            continue
        schema_errors = schema_findings("acceptance_record.schema.json", record, ref)
        findings.extend(schema_errors)
        if schema_errors or not isinstance(record, dict):
            continue
        prior_errors = sum(item["severity"] == "error" for item in findings)
        _validate_acceptance_record(record, claims, specs, results, finding_map, ref, findings)
        current_errors = sum(item["severity"] == "error" for item in findings)
        if current_errors == prior_errors:
            currentness = acceptance_currentness(
                record,
                claims=claims,
                specs=specs,
                results=results,
                findings=finding_map,
            )
            if not currentness["current"]:
                _finding(
                    findings,
                    "warning",
                    "acceptance_not_current",
                    "historical acceptance is not current: " + ", ".join(currentness["stale_reasons"]),
                    ref,
                )


def _validate_acceptance_record(
    record: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
    finding_map: dict[str, dict[str, Any]],
    ref: str,
    findings: list[dict[str, str]],
) -> None:
    digest_input = dict(record)
    acceptance_digest = digest_input.pop("acceptance_digest", None)
    if acceptance_digest != sha256_json(digest_input):
        _finding(findings, "error", "acceptance_digest_mismatch", "acceptance record digest is invalid", ref)
    claim = claims.get(str(record.get("claim_ref") or ""))
    claim_snapshot = record.get("claim_snapshot")
    if claim is None or not isinstance(claim_snapshot, dict) or claim_snapshot.get("claim_id") != record.get("claim_ref"):
        _finding(findings, "error", "accepted_claim_missing", "accepted Claim or its snapshot is missing", ref)
        return
    if record.get("claim_digest") != sha256_json(claim_snapshot):
        _finding(findings, "error", "accepted_claim_digest_mismatch", "accepted Claim snapshot digest is invalid", ref)
    profile_ref = record.get("profile_ref", {})
    try:
        profile = load_acceptance_profile(str(profile_ref.get("profile_id")), str(profile_ref.get("version")))
    except Exception as exc:
        _finding(findings, "error", "acceptance_profile_error", str(exc), ref)
        return
    if record.get("profile_digest") != sha256_json(profile):
        _finding(findings, "error", "acceptance_profile_digest_mismatch", "acceptance profile digest changed", ref)
    selected_specs = set(record.get("validation_spec_refs", []))
    snapshot_specs = set(claim_snapshot.get("validation_spec_refs", []))
    if profile.get("require_all_attached_specs") is True and selected_specs != snapshot_specs:
        _finding(findings, "error", "acceptance_spec_coverage", "acceptance does not cover every GateSpec attached in the Claim snapshot", ref)
    spec_digests = record.get("validation_spec_digests", {})
    if set(spec_digests) != selected_specs or any(
        spec_id not in specs or spec_digests[spec_id] != sha256_json(specs[spec_id])
        for spec_id in selected_specs
    ):
        _finding(findings, "error", "acceptance_spec_digest_mismatch", "acceptance GateSpec snapshot is invalid", ref)
    selected_results = [results.get(result_id) for result_id in record.get("validation_result_refs", [])]
    if any(result is None for result in selected_results):
        _finding(findings, "error", "acceptance_unknown_result", "acceptance references an unknown ValidationResult", ref)
        return
    result_digests = record.get("validation_result_digests", {})
    selected_result_refs = set(record.get("validation_result_refs", []))
    if set(result_digests) != selected_result_refs or any(
        result_id not in results or result_digests[result_id] != sha256_json(results[result_id])
        for result_id in selected_result_refs
    ):
        _finding(findings, "error", "acceptance_result_digest_mismatch", "acceptance ValidationResult snapshot is invalid", ref)
    snapshot_findings = record.get("finding_snapshot", [])
    if not isinstance(snapshot_findings, list) or any(not isinstance(item, dict) for item in snapshot_findings):
        _finding(findings, "error", "acceptance_finding_snapshot_mismatch", "acceptance Finding snapshot is invalid", ref)
        return
    snapshot_ids = [str(item.get("finding_id")) for item in snapshot_findings]
    if len(snapshot_ids) != len(set(snapshot_ids)) or any(record["claim_ref"] not in item.get("claim_refs", []) for item in snapshot_findings):
        _finding(findings, "error", "acceptance_finding_snapshot_mismatch", "acceptance Finding snapshot has duplicate or unrelated records", ref)
    if record.get("finding_snapshot_digest") != sha256_json(snapshot_findings):
        _finding(findings, "error", "acceptance_finding_digest_mismatch", "acceptance Finding snapshot digest is invalid", ref)
    selected_spec_records = [specs[spec_id] for spec_id in record.get("validation_spec_refs", []) if spec_id in specs]
    for code, message in acceptance_policy_violations(
        claim_snapshot=claim_snapshot,
        profile=profile,
        specs=selected_spec_records,
        results=[item for item in selected_results if isinstance(item, dict)],
        findings=snapshot_findings,
    ):
        _finding(findings, "error", code, message, ref)


def _unique_map(
    rows: Any,
    id_field: str,
    source: str,
    findings: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return values
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get(id_field)
        if not isinstance(identifier, str) or not identifier:
            continue
        if identifier in values:
            _finding(findings, "error", "duplicate_identifier", f"duplicate {id_field}: {identifier}", source)
        values[identifier] = row
    return values


def _require_refs(
    refs: Any,
    known: dict[str, Any],
    label: str,
    source: str,
    findings: list[dict[str, str]],
) -> None:
    if not isinstance(refs, list):
        return
    unknown = sorted(str(ref) for ref in refs if ref not in known)
    if unknown:
        _finding(findings, "error", "unknown_reference", f"{label} contains unknown refs: " + ", ".join(unknown), source)


def _find_cycle(nodes: set[str], edges: list[tuple[str, str]]) -> list[str]:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(node: str) -> list[str]:
        if node in active_set:
            index = active.index(node)
            return active[index:] + [node]
        if node in visited:
            return []
        active.append(node)
        active_set.add(node)
        for target in adjacency[node]:
            cycle = visit(target)
            if cycle:
                return cycle
        active.pop()
        active_set.remove(node)
        visited.add(node)
        return []

    for node in sorted(nodes):
        cycle = visit(node)
        if cycle:
            return cycle
    return []


def _datatype_matches(datatype: Any, value: Any) -> bool:
    if datatype == "boolean":
        return isinstance(value, bool)
    if datatype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if datatype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if datatype == "string":
        return isinstance(value, str)
    if datatype == "string_array":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if datatype == "number_array":
        return isinstance(value, list) and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    if datatype == "object":
        return isinstance(value, dict)
    return datatype == "json"


def _finding(findings: list[dict[str, str]], severity: str, code: str, message: str, path: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message, "path": path})


def _result(findings: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": "ts-workspace-validation/4",
        "valid": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
    }
