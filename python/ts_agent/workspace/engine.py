"""Transactional Phase, ResearchNode DAG, and Claim graph mutation engine."""

from __future__ import annotations

import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from ts_agent.validation import builtin_predicate_registry, evaluate_proof_spec

from .acceptance import project_acceptances
from .claims import claim_is_testable, claim_preregistration_digest
from .decision import _compile_change, validate_decision, validate_decision_binding
from .errors import ContractError
from .identity import WorkspaceIdentityError, ensure_workspace_identity
from ts_agent.io import now_iso, read_json, write_json
from .operational import node_completion_blockers, operational_snapshot
from .revision import workspace_revision
from .state import (
    CLAIMS_FILE,
    CLAIM_RELATIONS_FILE,
    OBSERVATIONS_FILE,
    FINDINGS_FILE,
    OPTIONAL_DIRS,
    RESEARCH_PHASES_FILE,
    RESEARCH_NODES_FILE,
    RESEARCH_STATE_FILE,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    STATE_FILES,
    VALIDATION_RESULTS_FILE,
    PROOF_SPECS_FILE,
    WORKSPACE_FILE,
    initial_documents,
)
from .transactions import (
    TRANSACTION_DIR,
    WORKSPACE_LOCK,
    commit_transaction,
    committed_decision_result,
    recover_incomplete_transactions,
    workspace_lock,
)
from .validator import validate_workspace


DRY_RUN_EXCLUDED_DIRS = frozenset({
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


def init_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    if root_path.is_symlink():
        raise ContractError("workspace root cannot be a symbolic link")
    existing = [name for name in REQUIRED_FILES if (root_path / name).exists()]
    if existing:
        raise ContractError("workspace already contains canonical state: " + ", ".join(sorted(existing)))
    root_path.mkdir(parents=True, exist_ok=True)
    try:
        identity = ensure_workspace_identity(root_path)
    except WorkspaceIdentityError as exc:
        raise ContractError(str(exc)) from exc
    created_at = now_iso()
    for dirname in REQUIRED_DIRS | OPTIONAL_DIRS:
        (root_path / dirname).mkdir(parents=True, exist_ok=True)
    for name, document in initial_documents(identity["workspace_id"], created_at).items():
        write_json(root_path / name, document)
    (root_path / "decision_log.jsonl").touch(mode=0o600)
    (root_path / "transaction_log.jsonl").touch(mode=0o600)
    validation = validate_workspace(root_path)
    if not validation["valid"]:
        raise ContractError("fresh workspace failed validation: " + _error_messages(validation))
    return {
        "schema_version": "ts-workspace-init-result/6",
        "root": str(root_path),
        "workspace_id": identity["workspace_id"],
        "created": True,
        "valid": True,
    }


def _apply_decision(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    validate_decision(decision)
    with workspace_lock(root_path):
        recover_incomplete_transactions(root_path)
        replay = committed_decision_result(root_path, decision)
        if replay is not None:
            return replay
        validate_decision_binding(root_path, decision)
        _validate_decision_dry_run_bound(root_path, decision)
        return _apply_once(root_path, decision)


def change_workspace(
    root: str | Path,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Compile, validate, and atomically apply one Root change.

    Callers never receive a compiled Decision that they must copy between
    mutation tools.  Compilation and the complete dry-run occur under the
    same workspace lock as the final commit, so the revision checked by the
    kernel is the revision that is changed.
    """

    root_path = Path(root).expanduser().resolve()
    with workspace_lock(root_path):
        recover_incomplete_transactions(root_path)
        compiled = _compile_change(root_path, request)
        decision = compiled["decision"]
        _validate_decision_dry_run_bound(root_path, decision)
        result = _apply_once(root_path, decision)
        return {
            "schema_version": "ts-change-result/1",
            "change_id": decision["decision_id"],
            "allocated_refs": compiled["allocated_refs"],
            "operation_count": result["operation_count"],
            "created_refs": result["created_refs"],
            "workspace_revision": workspace_revision(root_path),
            "mutation_applied": True,
        }


def _validate_decision_dry_run(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    validate_decision_binding(root_path, decision)
    return _validate_decision_dry_run_bound(root_path, decision)


def _validate_decision_dry_run_bound(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ts-workspace-dry-run-") as temporary:
        target = Path(temporary) / "workspace"
        shutil.copytree(root, target, ignore=_ignore_dry_run_entries, symlinks=True)
        result = _apply_once(target, decision)
        validation = validate_workspace(target)
        if not validation["valid"]:
            raise ContractError("decision dry run produced an invalid workspace: " + _error_messages(validation))
        created_acceptances = set(result["created_refs"]["acceptances"])
        if created_acceptances:
            documents = {name: read_json(target / name) for name in STATE_FILES}
            state = documents[RESEARCH_STATE_FILE]
            projections = project_acceptances(target, state["acceptance_refs"], documents)
            stale_created = [
                item for item in projections
                if item["acceptance_id"] in created_acceptances and not item["current"]
            ]
            if stale_created:
                details = "; ".join(
                    f"{item['acceptance_id']}: {', '.join(item['stale_reasons'])}"
                    for item in stale_created
                )
                raise ContractError("decision creates a non-current acceptance record: " + details)
        return {
            "schema_version": "ts-decision-validation-result/1",
            "valid": True,
            "decision_id": decision["decision_id"],
            "result": result,
            "post_validation": validation,
        }


def _apply_once(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    documents = {name: deepcopy(read_json(root / name)) for name in STATE_FILES}
    phases = _map(documents[RESEARCH_PHASES_FILE]["phases"], "phase_id")
    claims = _map(documents[CLAIMS_FILE]["claims"], "claim_id")
    relations = _map(documents[CLAIM_RELATIONS_FILE]["relations"], "relation_id")
    nodes = _map(documents[RESEARCH_NODES_FILE]["nodes"], "node_id")
    observations = _map(documents[OBSERVATIONS_FILE]["observations"], "observation_id")
    specs = _map(documents[PROOF_SPECS_FILE]["proofs"], "proof_id")
    results = _map(documents[VALIDATION_RESULTS_FILE]["results"], "result_id")
    findings = _map(documents[FINDINGS_FILE]["findings"], "finding_id")
    operational = operational_snapshot(root)
    accepted_changes: dict[Path, Any] = {}
    created_refs = {
        "phases": [],
        "claims": [],
        "relations": [],
        "nodes": [],
        "observations": [],
        "findings": [],
        "proof_specs": [],
        "validation_results": [],
        "acceptances": [],
    }

    for operation in decision["operations"]:
        name = operation["op"]
        if name == "append_research_phase":
            record = deepcopy(operation["record"])
            _require_new(record["phase_id"], phases, "ResearchPhase")
            phases[record["phase_id"]] = record
            documents[RESEARCH_PHASES_FILE]["phases"].append(record)
            created_refs["phases"].append(record["phase_id"])
        elif name == "append_claim":
            record = deepcopy(operation["record"])
            _require_new(record["claim_id"], claims, "Claim")
            if record.get("preregistration_digest") != claim_preregistration_digest(record):
                raise ContractError(f"Claim pre-registration digest mismatch: {record['claim_id']}")
            if record["created_by_node"] is not None:
                _require_known([record["created_by_node"]], nodes, "Claim created_by_node")
            claims[record["claim_id"]] = record
            documents[CLAIMS_FILE]["claims"].append(record)
            created_refs["claims"].append(record["claim_id"])
        elif name == "append_claim_relation":
            record = deepcopy(operation["record"])
            _require_new(record["relation_id"], relations, "Claim relation")
            _require_known([record["source_claim_ref"], record["target_claim_ref"]], claims, "Claim relation endpoints")
            relations[record["relation_id"]] = record
            documents[CLAIM_RELATIONS_FILE]["relations"].append(record)
            created_refs["relations"].append(record["relation_id"])
        elif name == "append_research_node":
            record = deepcopy(operation["record"])
            _require_new(record["node_id"], nodes, "ResearchNode")
            _require_known([record["phase_ref"]], phases, "ResearchNode phase_ref")
            _require_known(record["dependency_refs"], nodes, "ResearchNode dependency_refs")
            _require_known(record["claim_refs"], claims, "ResearchNode claim_refs")
            if record["primary_claim_ref"] is not None and record["primary_claim_ref"] not in record["claim_refs"]:
                raise ContractError("ResearchNode primary_claim_ref must appear in claim_refs")
            nodes[record["node_id"]] = record
            documents[RESEARCH_NODES_FILE]["nodes"].append(record)
            created_refs["nodes"].append(record["node_id"])
        elif name == "append_observation":
            record = deepcopy(operation["record"])
            _require_new(record["observation_id"], observations, "Observation")
            node = _require_open_node(nodes, record["created_by_node"], "Observation")
            if record.get("candidate_ref") is not None:
                from .candidates import validate_promoted_candidate

                validate_promoted_candidate(root, record)
            observations[record["observation_id"]] = record
            documents[OBSERVATIONS_FILE]["observations"].append(record)
            _append_unique(node["observation_refs"], record["observation_id"])
            created_refs["observations"].append(record["observation_id"])
        elif name == "append_finding":
            record = deepcopy(operation["record"])
            _require_new(record["finding_id"], findings, "Finding")
            _require_known(record["claim_refs"], claims, "Finding claim_refs")
            _require_known(record["node_refs"], nodes, "Finding node_refs")
            _require_known(record["basis_observation_refs"], observations, "Finding basis_observation_refs")
            findings[record["finding_id"]] = record
            documents[FINDINGS_FILE]["findings"].append(record)
            for node_ref in record["node_refs"]:
                _append_unique(nodes[node_ref]["finding_refs"], record["finding_id"])
            created_refs["findings"].append(record["finding_id"])
        elif name == "append_proof_spec":
            record = deepcopy(operation["record"])
            _require_new(record["proof_id"], specs, "ProofSpec")
            claim = _require_claim(claims, record["target_claim_ref"])
            if not claim_is_testable(claim):
                raise ContractError("ProofSpec requires a Claim with pre-registered predictions and falsifiers")
            if record.get("claim_preregistration_digest") != claim.get("preregistration_digest"):
                raise ContractError(
                    f"ProofSpec Claim pre-registration binding mismatch: {record['proof_id']}"
                )
            node = _require_open_node(nodes, record["created_by_node"], "ProofSpec")
            expected = dict(record)
            digest = expected.pop("proof_digest")
            from ts_agent.io import sha256_json

            if digest != sha256_json(expected):
                raise ContractError(f"ProofSpec digest mismatch: {record['proof_id']}")
            specs[record["proof_id"]] = record
            documents[PROOF_SPECS_FILE]["proofs"].append(record)
            _append_unique(claim["proof_spec_refs"], record["proof_id"])
            _append_unique(node["proof_spec_refs"], record["proof_id"])
            created_refs["proof_specs"].append(record["proof_id"])
        elif name == "append_validation_result":
            record = deepcopy(operation["record"])
            _require_new(record["result_id"], results, "ValidationResult")
            spec = specs.get(record["proof_ref"])
            if spec is None:
                raise ContractError(f"ValidationResult references unknown ProofSpec: {record['proof_ref']}")
            node = _require_open_node(nodes, record["evaluated_by_node"], "ValidationResult")
            claim = _require_claim(claims, record["target_claim_ref"])
            _require_known(record["observation_refs"], observations, "ValidationResult observation_refs")
            expected = evaluate_proof_spec(
                spec,
                [observations[ref] for ref in record["observation_refs"]],
                result_id=record["result_id"],
                evaluated_by_node=record["evaluated_by_node"],
                evaluated_by_decision=record["evaluated_by_decision"],
                registry=builtin_predicate_registry(),
                evaluated_at=record["evaluated_at"],
            )
            if expected != record:
                raise ContractError(f"ValidationResult differs from deterministic evaluation: {record['result_id']}")
            results[record["result_id"]] = record
            documents[VALIDATION_RESULTS_FILE]["results"].append(record)
            _append_unique(claim["validation_result_refs"], record["result_id"])
            _append_unique(node["validation_result_refs"], record["result_id"])
            created_refs["validation_results"].append(record["result_id"])
        elif name == "update_claim":
            claim = _require_claim(claims, operation["claim_ref"])
            _require_known(operation["observation_refs"], observations, "Claim update observation_refs")
            _require_known(operation["validation_result_refs"], results, "Claim update validation_result_refs")
            for result_ref in operation["validation_result_refs"]:
                if results[result_ref]["target_claim_ref"] != claim["claim_id"]:
                    raise ContractError(f"Claim update cites a ValidationResult for another Claim: {result_ref}")
            if operation["status"] == "supported" and not (operation["observation_refs"] or operation["validation_result_refs"]):
                raise ContractError("supported Claim update requires cited Observations or ValidationResults")
            if operation["status"] in {"supported", "contradicted", "inconclusive"} and not claim_is_testable(claim):
                raise ContractError(
                    f"{operation['status']} Claim update requires pre-registered predictions and falsifiers"
                )
            claim["status"] = operation["status"]
            for ref in operation["observation_refs"]:
                _append_unique(claim["observation_refs"], ref)
            for ref in operation["validation_result_refs"]:
                _append_unique(claim["validation_result_refs"], ref)
            claim["history"].append({
                "status": operation["status"],
                "summary": operation["summary"],
                "observation_refs": list(operation["observation_refs"]),
                "validation_result_refs": list(operation["validation_result_refs"]),
                "decision_id": decision["decision_id"],
                "created_at": operation["updated_at"],
            })
        elif name == "complete_research_node":
            node = _require_open_node(nodes, operation["node_ref"], "completion")
            blockers = node_completion_blockers(
                operational,
                node_id=operation["node_ref"],
                outcome=operation["outcome"],
            )
            if blockers:
                details = "; ".join(f"[{item['code']}] {item['message']}" for item in blockers[:8])
                raise ContractError(f"ResearchNode completion is blocked: {details}")
            node["status"] = operation["outcome"]
            node["result"] = {
                "outcome": operation["outcome"],
                "summary": operation["summary"],
                "open_questions": list(operation["open_questions"]),
                "decision_id": decision["decision_id"],
                "completed_at": operation["completed_at"],
            }
        elif name == "resolve_finding":
            finding = findings.get(operation["finding_ref"])
            if finding is None:
                raise ContractError(f"unknown Finding: {operation['finding_ref']}")
            if finding["status"] != "open":
                raise ContractError(f"Finding is already terminal: {operation['finding_ref']}")
            _require_known(operation["basis_observation_refs"], observations, "Finding resolution observations")
            finding["status"] = operation["status"]
            finding["resolution"] = {
                "status": operation["status"],
                "summary": operation["summary"],
                "basis_observation_refs": list(operation["basis_observation_refs"]),
                "decision_id": decision["decision_id"],
                "resolved_at": operation["resolved_at"],
            }
        elif name == "set_focus":
            _require_known(operation["claim_refs"], claims, "focus Claim refs")
            _require_known(operation["node_refs"], nodes, "focus ResearchNode refs")
            documents[RESEARCH_STATE_FILE]["focus_claim_refs"] = list(operation["claim_refs"])
            documents[RESEARCH_STATE_FILE]["focus_node_refs"] = list(operation["node_refs"])
        elif name == "accept_claim":
            record = deepcopy(operation["record"])
            acceptance_id = record["acceptance_id"]
            acceptance_ref = f"acceptances/{acceptance_id}.json"
            if (root / acceptance_ref).exists() or acceptance_ref in documents[RESEARCH_STATE_FILE]["acceptance_refs"]:
                raise ContractError(f"acceptance already exists: {acceptance_id}")
            accepted_changes[root / acceptance_ref] = record
            documents[RESEARCH_STATE_FILE]["acceptance_refs"].append(acceptance_ref)
            created_refs["acceptances"].append(acceptance_id)
        else:
            raise ContractError(f"unsupported Decision operation: {name}")

    changes = {root / name: documents[name] for name in STATE_FILES if name != WORKSPACE_FILE}
    changes.update(accepted_changes)
    result = {
        "schema_version": "ts-decision-apply-result/1",
        "decision_id": decision["decision_id"],
        "operation_count": len(decision["operations"]),
        "created_refs": created_refs,
        "mutation_applied": True,
    }
    commit_transaction(root, decision, changes, result)
    return result


def _ignore_dry_run_entries(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in DRY_RUN_EXCLUDED_DIRS}


def _map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows if isinstance(row, dict) and isinstance(row.get(key), str)}


def _require_new(identifier: str, known: dict[str, Any], label: str) -> None:
    if identifier in known:
        raise ContractError(f"{label} already exists: {identifier}")


def _require_known(refs: list[str], known: dict[str, Any], label: str) -> None:
    unknown = sorted(set(refs) - set(known))
    if unknown:
        raise ContractError(f"{label} contains unknown refs: " + ", ".join(unknown))


def _require_claim(claims: dict[str, dict[str, Any]], claim_ref: str) -> dict[str, Any]:
    try:
        return claims[claim_ref]
    except KeyError as exc:
        raise ContractError(f"unknown Claim: {claim_ref}") from exc


def _require_open_node(nodes: dict[str, dict[str, Any]], node_ref: str, operation: str) -> dict[str, Any]:
    node = nodes.get(node_ref)
    if node is None:
        raise ContractError(f"{operation} references unknown ResearchNode: {node_ref}")
    if node.get("status") != "open":
        raise ContractError(f"{operation} requires an open ResearchNode: {node_ref}")
    return node


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _error_messages(validation: dict[str, Any]) -> str:
    messages = [
        str(item.get("message"))
        for item in validation.get("findings", [])
        if isinstance(item, dict) and item.get("severity") == "error"
    ]
    return "; ".join(messages[:8]) or "unknown validation error"
