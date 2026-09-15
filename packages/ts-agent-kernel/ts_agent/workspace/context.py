"""Revision-aware graph projections for Root, Review, UI, and reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ts_agent.validation.registry import (
    RegistryError,
    builtin_predicate_registry,
    list_acceptance_profiles,
    list_proof_templates,
    load_proof_template,
)

from .acceptance import project_acceptances
from .associations import derive_claim_node_links
from ts_agent.io import read_json, sha256_json
from .operational import operational_snapshot
from .node_contract import node_contract_digest
from .refs import (
    acceptance_sort_key,
    node_sort_key,
    claim_relation_sort_key,
    claim_sort_key,
    finding_sort_key,
    observation_sort_key,
    phase_sort_key,
    validation_result_sort_key,
    proof_spec_sort_key,
)
from .revision import report_id_for_revision, workspace_revision_from_documents
from .trajectory import project_research_trajectory
from .state import (
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
)
from .validator import validate_workspace
from .path_safety import has_symlink_component, lexical_path, path_has_symlink


CONTEXT_MODES = frozenset({"frontier", "claim", "node", "subgraph", "finding", "proof", "delta"})
DEFAULT_LIMITS = {
    "phases": 12,
    "claims": 12,
    "relations": 24,
    "nodes": 16,
    "observations": 48,
    "specs": 24,
    "results": 24,
    "findings": 24,
    "acceptances": 16,
    "decisions": 8,
}
MAX_CONTEXT_CALCULATION_ATTEMPTS = 32
MAX_CONTEXT_ATTEMPT_INTEGRITY_FINDINGS = 24
MAX_CONTEXT_OPERATIONAL_INTEGRITY_FINDINGS = 24
MAX_BRIEF_ATTEMPTS_PER_NODE = 8


class ContextCompileError(ValueError):
    """Raised when a graph projection request is invalid."""


def compile_context(
    root: str | Path,
    *,
    mode: str = "frontier",
    claim_ref: str | None = None,
    node_ref: str | None = None,
    finding_ref: str | None = None,
    proof_ref: str | None = None,
    claim_refs: list[str] | None = None,
    node_refs: list[str] | None = None,
    depth: int = 1,
    since_revision: str | None = None,
    since_operational_revision: str | None = None,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    if mode not in CONTEXT_MODES:
        raise ContextCompileError(f"unsupported context mode: {mode}")
    if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 4:
        raise ContextCompileError("context depth must be between 0 and 4")
    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise ContextCompileError(f"workspace root contains a symbolic link: {root_path}")
    documents = _read_state_documents(root_path)
    revision = workspace_revision_from_documents(documents)
    operations = operational_snapshot(root_path)

    if mode == "delta" and since_revision == revision and since_operational_revision == operations["operational_revision"]:
        return {
            "schema_version": "ts-context-projection/3",
            "mode": "delta",
            "changed": False,
            "scientific_changed": False,
            "operational_changed": False,
            "workspace_revision": revision,
            "operational_revision": operations["operational_revision"],
            "projection_id": _projection_id({"mode": "delta", "workspace_revision": revision}),
            "retrieval": {"next_modes": ["frontier"]},
        }

    query_mode = "frontier" if mode == "delta" else mode
    selected = _select_graph(
        documents,
        mode=query_mode,
        claim_ref=claim_ref,
        node_ref=node_ref,
        finding_ref=finding_ref,
        proof_ref=proof_ref,
        claim_refs=claim_refs or [],
        node_refs=node_refs or [],
        depth=depth,
    )
    state = documents[RESEARCH_STATE_FILE]
    all_acceptances = project_acceptances(root_path, state["acceptance_refs"], documents)
    selected_claim_refs = {str(item["claim_id"]) for item in selected["claims"]}
    selected["acceptances"] = [
        item for item in all_acceptances if item.get("claim_ref") in selected_claim_refs
    ]
    bounded, omitted = _bound_selection(selected, {**DEFAULT_LIMITS, **(limits or {})})
    trajectory = project_research_trajectory(
        root_path,
        bounded["research_phases"],
        bounded["research_nodes"],
    )
    selected_node_ids = {str(item["node_id"]) for item in bounded["research_nodes"]}
    compact_attempts, omitted_attempts = _compact_calculation_attempts(
        operations["calculation_attempts"],
        selected_node_ids,
        limit=MAX_CONTEXT_CALCULATION_ATTEMPTS,
    )
    omitted["calculation_attempts"] = omitted_attempts
    attempt_integrity_findings, omitted_attempt_integrity = _compact_attempt_integrity_findings(
        operations["calculation_attempt_integrity_findings"],
        selected_node_ids,
        limit=MAX_CONTEXT_ATTEMPT_INTEGRITY_FINDINGS,
    )
    omitted["calculation_attempt_integrity_findings"] = omitted_attempt_integrity
    operational_integrity_findings, omitted_operational_integrity = _compact_operational_integrity_findings(
        operations.get("operational_integrity_findings", []),
        selected_node_ids,
        limit=MAX_CONTEXT_OPERATIONAL_INTEGRITY_FINDINGS,
    )
    omitted["operational_integrity_findings"] = omitted_operational_integrity
    activity_summaries = [
        item
        for item in operations["activity_summaries"]
        if item.get("node_id") in selected_node_ids
        and (item.get("activity_count") or item.get("integrity_error_count"))
    ]
    recent_decisions, omitted_decisions = _recent_decisions(root_path, (limits or {}).get("decisions", DEFAULT_LIMITS["decisions"]))
    omitted["decisions"] = omitted_decisions
    validation = validate_workspace(root_path)
    current_acceptance_refs = [str(item["ref"]) for item in all_acceptances if item["current"]]
    stale_acceptance_refs = [str(item["ref"]) for item in all_acceptances if not item["current"]]
    workspace_brief = _workspace_brief(
        bounded,
        trajectory=trajectory,
        activity_summaries=activity_summaries,
        calculation_attempts=compact_attempts,
        calculation_attempt_integrity_findings=attempt_integrity_findings,
        current_acceptances=all_acceptances,
    )
    payload = {
        "schema_version": "ts-context-projection/3",
        "mode": mode,
        "changed": True if mode == "delta" else None,
        "scientific_changed": (since_revision != revision) if mode == "delta" else None,
        "operational_changed": (
            since_operational_revision != operations["operational_revision"]
            if mode == "delta" and since_operational_revision is not None
            else None
        ),
        "workspace_id": documents[WORKSPACE_FILE]["workspace_id"],
        "report_id": report_id_for_revision(revision),
        "workspace_revision": revision,
        "operational_revision": operations["operational_revision"],
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "claim_refs": list(state["focus_claim_refs"]),
            "node_refs": list(state["focus_node_refs"]),
        },
        "acceptance_summary": {
            "record_refs": list(state["acceptance_refs"]),
            "current_refs": current_acceptance_refs,
            "stale_refs": stale_acceptance_refs,
        },
        "workspace_brief": workspace_brief,
        **bounded,
        "open_findings": [item for item in bounded["findings"] if item.get("status") == "open"],
        "incomplete_proof": _incomplete_proof(bounded["proof_specs"], bounded["validation_results"]),
        "unresolved_controls": operations["unresolved_controls"],
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "activity_summaries": activity_summaries,
        "node_dispatch": [row for row in operations.get("node_dispatch", []) if row["node_id"] in selected_node_ids],
        # This is an operational, bounded projection.  It is intentionally
        # excluded from ``scientific_binding`` so scheduler churn does not
        # invalidate the scientific context projection ID.
        "calculation_attempts": compact_attempts,
        "calculation_attempt_integrity_findings": attempt_integrity_findings,
        "operational_integrity_findings": operational_integrity_findings,
        "operational_summary": operations["operational_summary"],
        "recent_decisions": recent_decisions,
        "omitted": omitted,
        "retrieval": _retrieval_hints(mode, bounded, omitted),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    # ``workspace_brief`` is intentionally a mixed projection: its Node rows
    # carry both canonical navigation fields and operational activity/Attempt
    # summaries for the Root.  Only the canonical portion belongs in the
    # scientific projection binding.  Otherwise a queued->running scheduler
    # update would invalidate a Decision context even though no scientific
    # record changed.  Keep the complete mixed brief in the returned payload;
    # strip only operational fields while computing the content identity.
    scientific_brief = _scientific_workspace_brief(workspace_brief)
    scientific_omitted = {
        key: value
        for key, value in omitted.items()
        if key not in {
            "calculation_attempts",
            "calculation_attempt_integrity_findings",
            "operational_integrity_findings",
        }
    }
    scientific_binding = {
        "mode": payload["mode"],
        "workspace_revision": payload["workspace_revision"],
        "focus": payload["focus"],
        "acceptance_summary": payload["acceptance_summary"],
        "workspace_brief": scientific_brief,
        "research_phases": payload["research_phases"],
        "claims": payload["claims"],
        "claim_relations": payload["claim_relations"],
        "research_nodes": payload["research_nodes"],
        "observations": payload["observations"],
        "proof_specs": payload["proof_specs"],
        "validation_results": payload["validation_results"],
        "findings": payload["findings"],
        "acceptances": payload["acceptances"],
        "recent_decisions": payload["recent_decisions"],
        "omitted": scientific_omitted,
    }
    payload["projection_id"] = _projection_id(scientific_binding)
    return payload


def proof_capabilities(
    *,
    template_id: str | None = None,
    template_version: str | None = None,
) -> dict[str, Any]:
    if (template_id is None) != (template_version is None):
        raise ContextCompileError("focused validation capabilities require template_id and template_version together")
    registry = builtin_predicate_registry()
    payload = {
        "schema_version": "ts-proof-capabilities/1",
        "predicates": registry.capabilities,
        "predicate_registry_digest": registry.digest,
        "templates": list_proof_templates(),
        "acceptance_profiles": list_acceptance_profiles(),
        "agent_supplied_executable_code": False,
    }
    if template_id is not None and template_version is not None:
        try:
            template = load_proof_template(template_id, template_version)
        except RegistryError as exc:
            raise ContextCompileError(str(exc)) from exc
        payload["selected_template"] = {
            **template,
            "digest": sha256_json(template),
        }
    return payload


def build_review_snapshot(root: str | Path, *, target_claim_ref: str, depth: int = 2) -> dict[str, Any]:
    projection = compile_context(root, mode="claim", claim_ref=target_claim_ref, depth=depth, limits={
        "claims": 32,
        "relations": 64,
        "nodes": 32,
        "observations": 128,
        "specs": 64,
        "results": 64,
        "findings": 64,
        "acceptances": 32,
        "decisions": 0,
    })
    dependency_refs = {
        "phase_refs": sorted(
            (str(item["phase_id"]) for item in projection["research_phases"]),
            key=phase_sort_key,
        ),
        "claim_refs": sorted(
            (str(item["claim_id"]) for item in projection["claims"]),
            key=claim_sort_key,
        ),
        "relation_refs": sorted(
            (str(item["relation_id"]) for item in projection["claim_relations"]),
            key=claim_relation_sort_key,
        ),
        "node_refs": sorted(
            (str(item["node_id"]) for item in projection["research_nodes"]),
            key=node_sort_key,
        ),
        "observation_refs": sorted(
            (str(item["observation_id"]) for item in projection["observations"]),
            key=observation_sort_key,
        ),
        "proof_spec_refs": sorted(
            (str(item["proof_id"]) for item in projection["proof_specs"]),
            key=proof_spec_sort_key,
        ),
        "validation_result_refs": sorted(
            (str(item["result_id"]) for item in projection["validation_results"]),
            key=validation_result_sort_key,
        ),
        "finding_refs": sorted(
            (str(item["finding_id"]) for item in projection["findings"]),
            key=finding_sort_key,
        ),
        "acceptance_refs": sorted(
            (str(item["acceptance_id"]) for item in projection["acceptances"]),
            key=acceptance_sort_key,
        ),
    }
    return {
        "schema_version": "ts-review-snapshot/4",
        "report_id": projection["report_id"],
        "workspace_revision": projection["workspace_revision"],
        "projection_id": projection["projection_id"],
        "target_claim_ref": target_claim_ref,
        "research_phases": projection["research_phases"],
        "claims": projection["claims"],
        "claim_relations": projection["claim_relations"],
        "research_nodes": projection["research_nodes"],
        "observations": projection["observations"],
        "proof_specs": projection["proof_specs"],
        "validation_results": projection["validation_results"],
        "findings": projection["findings"],
        "acceptances": projection["acceptances"],
        "dependency_refs": dependency_refs,
        "omitted": projection["omitted"],
    }


def _select_graph(
    documents: dict[str, dict[str, Any]],
    *,
    mode: str,
    claim_ref: str | None,
    node_ref: str | None,
    finding_ref: str | None,
    proof_ref: str | None,
    claim_refs: list[str],
    node_refs: list[str],
    depth: int,
) -> dict[str, list[dict[str, Any]]]:
    phases = _map(documents[RESEARCH_PHASES_FILE]["phases"], "phase_id")
    claims = _map(documents[CLAIMS_FILE]["claims"], "claim_id")
    relations = _map(documents[CLAIM_RELATIONS_FILE]["relations"], "relation_id")
    nodes = _map(documents[RESEARCH_NODES_FILE]["nodes"], "node_id")
    observations = _map(documents[OBSERVATIONS_FILE]["observations"], "observation_id")
    specs = _map(documents[PROOF_SPECS_FILE]["proofs"], "proof_id")
    results = _map(documents[VALIDATION_RESULTS_FILE]["results"], "result_id")
    findings = _map(documents[FINDINGS_FILE]["findings"], "finding_id")
    state = documents[RESEARCH_STATE_FILE]
    claim_node_links = derive_claim_node_links(claims.values(), nodes.values())

    selected_claims: set[str] = set()
    selected_nodes: set[str] = set()
    if mode == "frontier":
        selected_claims.update(str(ref) for ref in state["focus_claim_refs"])
        selected_nodes.update(str(ref) for ref in state["focus_node_refs"])
        selected_nodes.update(node_id for node_id, node in nodes.items() if node.get("status") == "open")
        selected_claims.update(
            claim_id
            for claim_id, node_id in claim_node_links
            if node_id in selected_nodes
        )
    elif mode == "claim":
        if claim_ref not in claims:
            raise ContextCompileError(f"unknown Claim: {claim_ref}")
        selected_claims.add(str(claim_ref))
    elif mode == "node":
        if node_ref not in nodes:
            raise ContextCompileError(f"unknown ResearchNode: {node_ref}")
        selected_nodes.add(str(node_ref))
        selected_claims.update(
            claim_id
            for claim_id, linked_node_id in claim_node_links
            if linked_node_id == node_ref
        )
    elif mode == "subgraph":
        unknown_claims = sorted(set(claim_refs) - set(claims), key=claim_sort_key)
        unknown_nodes = sorted(set(node_refs) - set(nodes), key=node_sort_key)
        if unknown_claims or unknown_nodes or not (claim_refs or node_refs):
            raise ContextCompileError("subgraph requires known claim_refs or node_refs")
        selected_claims.update(claim_refs)
        selected_nodes.update(node_refs)
    elif mode == "finding":
        if finding_ref not in findings:
            raise ContextCompileError(f"unknown Finding: {finding_ref}")
        record = findings[str(finding_ref)]
        selected_claims.update(str(ref) for ref in record.get("claim_refs", []))
        selected_nodes.update(str(ref) for ref in record.get("node_refs", []))
    elif mode == "proof":
        spec = specs.get(str(proof_ref))
        result = results.get(str(proof_ref))
        if spec is None and result is None:
            raise ContextCompileError(f"unknown proof ref: {proof_ref}")
        if result is not None:
            spec = specs.get(str(result.get("proof_ref")))
            selected_nodes.add(str(result.get("evaluated_by_node")))
        if spec is not None:
            selected_claims.add(str(spec.get("target_claim_ref")))
            selected_nodes.add(str(spec.get("created_by_node")))

    selected_claims = _expand_claims(selected_claims, relations.values(), depth)
    selected_nodes.update(
        node_id
        for claim_id, node_id in claim_node_links
        if claim_id in selected_claims
    )
    selected_nodes = _expand_nodes(selected_nodes, nodes, depth)
    selected_claims.update(
        claim_id
        for claim_id, node_id in claim_node_links
        if node_id in selected_nodes
    )

    selected_relations = [
        relation
        for relation in relations.values()
        if relation.get("source_claim_ref") in selected_claims and relation.get("target_claim_ref") in selected_claims
    ]
    selected_specs = [spec for spec in specs.values() if spec.get("target_claim_ref") in selected_claims]
    selected_proof_refs = {str(spec["proof_id"]) for spec in selected_specs}
    selected_results = [result for result in results.values() if result.get("proof_ref") in selected_proof_refs]
    selected_observation_refs = {
        str(ref)
        for node_id in selected_nodes
        for ref in nodes.get(node_id, {}).get("observation_refs", [])
    }
    selected_observation_refs.update(
        str(ref)
        for result in selected_results
        for ref in result.get("observation_refs", [])
    )
    selected_findings = [
        finding
        for finding in findings.values()
        if (
            set(str(ref) for ref in finding.get("claim_refs", [])).intersection(selected_claims)
            or set(str(ref) for ref in finding.get("node_refs", [])).intersection(selected_nodes)
            or (mode == "frontier" and finding.get("status") == "open")
            or finding.get("finding_id") == finding_ref
        )
    ]
    return {
        "research_phases": [
            phases[ref]
            for ref in sorted(
                {str(nodes[node_id]["phase_ref"]) for node_id in selected_nodes if node_id in nodes},
                key=phase_sort_key,
            )
            if ref in phases
        ],
        "claims": [claims[ref] for ref in sorted(selected_claims, key=claim_sort_key) if ref in claims],
        "claim_relations": sorted(
            selected_relations,
            key=lambda value: claim_relation_sort_key(str(value["relation_id"])),
        ),
        "research_nodes": [
            {
                **nodes[ref],
                "related_claim_refs": [
                    claim_id
                    for claim_id, node_id in claim_node_links
                    if node_id == ref
                ],
            }
            for ref in sorted(selected_nodes, key=node_sort_key)
            if ref in nodes
        ],
        "observations": [
            observations[ref]
            for ref in sorted(selected_observation_refs, key=observation_sort_key)
            if ref in observations
        ],
        "proof_specs": sorted(
            selected_specs,
            key=lambda value: proof_spec_sort_key(str(value["proof_id"])),
        ),
        "validation_results": sorted(
            selected_results,
            key=lambda value: validation_result_sort_key(str(value["result_id"])),
        ),
        "findings": sorted(
            selected_findings,
            key=lambda value: finding_sort_key(str(value["finding_id"])),
        ),
    }


def _expand_claims(seeds: set[str], relations: Iterable[dict[str, Any]], depth: int) -> set[str]:
    selected = set(seeds)
    relation_rows = list(relations)
    frontier = set(seeds)
    for _ in range(depth):
        next_frontier: set[str] = set()
        for relation in relation_rows:
            source = str(relation.get("source_claim_ref"))
            target = str(relation.get("target_claim_ref"))
            if source in frontier or target in frontier:
                next_frontier.update({source, target})
        next_frontier -= selected
        selected.update(next_frontier)
        frontier = next_frontier
    return selected


def _expand_nodes(seeds: set[str], nodes: dict[str, dict[str, Any]], depth: int) -> set[str]:
    selected = {ref for ref in seeds if ref in nodes}
    frontier = set(selected)
    for _ in range(depth):
        next_frontier = {
            str(dependency)
            for node_id in frontier
            for dependency in nodes[node_id].get("dependency_refs", [])
            if dependency in nodes
        }
        next_frontier.update(
            node_id
            for node_id, node in nodes.items()
            if set(str(ref) for ref in node.get("dependency_refs", [])).intersection(frontier)
        )
        next_frontier -= selected
        selected.update(next_frontier)
        frontier = next_frontier
    return selected


def _bound_selection(
    selected: dict[str, list[dict[str, Any]]],
    limits: dict[str, int],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    key_limits = {
        "research_phases": "phases",
        "claims": "claims",
        "claim_relations": "relations",
        "research_nodes": "nodes",
        "observations": "observations",
        "proof_specs": "specs",
        "validation_results": "results",
        "findings": "findings",
        "acceptances": "acceptances",
    }
    bounded: dict[str, list[dict[str, Any]]] = {}
    omitted: dict[str, int] = {}
    for key, values in selected.items():
        limit = limits[key_limits[key]]
        if not isinstance(limit, int) or limit < 0:
            raise ContextCompileError(f"invalid context limit: {key_limits[key]}")
        bounded[key] = values[:limit]
        omitted[key] = max(0, len(values) - limit)
    return bounded, omitted


def _recent_decisions(root: Path, limit: int) -> tuple[list[dict[str, Any]], int]:
    path = root / "decision_log.jsonl"
    if has_symlink_component(root, path) or path.is_symlink():
        return [], 0
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.is_file() else []:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    if limit <= 0:
        return [], len(rows)
    return rows[-limit:], max(0, len(rows) - limit)


def _read_state_documents(root: Path) -> dict[str, dict[str, Any]]:
    """Read canonical documents only when every path remains physical.

    Context is a read-only projection, but it is still an input boundary.  A
    symlinked canonical file must not be followed merely because the workspace
    directory itself is physical; otherwise external JSON could become part of
    a Claim/Observation projection and its digest.
    """

    documents: dict[str, dict[str, Any]] = {}
    for name in STATE_FILES:
        path = root / name
        if has_symlink_component(root, path) or path.is_symlink():
            raise ContextCompileError(f"workspace file contains a symbolic link: {name}")
        try:
            value = read_json(path)
        except (OSError, ValueError) as exc:
            raise ContextCompileError(f"cannot read workspace file {name}: {exc}") from exc
        if not isinstance(value, dict):
            raise ContextCompileError(f"workspace file is not an object: {name}")
        documents[name] = value
    return documents


def _incomplete_proof(specs: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = {str(result.get("proof_ref")): result for result in results}
    return [
        {
            "proof_ref": spec["proof_id"],
            "target_claim_ref": spec["target_claim_ref"],
            "dimension": spec["dimension"],
            "latest_verdict": latest.get(str(spec["proof_id"]), {}).get("verdict", "not_evaluated"),
        }
        for spec in specs
        if latest.get(str(spec["proof_id"]), {}).get("verdict") != "pass"
    ]


def _workspace_brief(
    selected: dict[str, list[dict[str, Any]]],
    *,
    trajectory: dict[str, Any],
    activity_summaries: list[dict[str, Any]],
    calculation_attempts: list[dict[str, Any]],
    calculation_attempt_integrity_findings: list[dict[str, Any]],
    current_acceptances: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes = selected["research_nodes"]
    claims = selected["claims"]
    findings = selected["findings"]
    current_claims = {
        str(item.get("claim_ref"))
        for item in current_acceptances
        if item.get("current") is True
    }
    activity_by_node = {
        str(item.get("node_id")): item
        for item in activity_summaries
        if isinstance(item.get("node_id"), str)
    }
    attempts_by_node: dict[str, list[dict[str, Any]]] = {}
    for item in calculation_attempts:
        node_id = item.get("node_id")
        if not isinstance(node_id, str):
            continue
        attempts_by_node.setdefault(node_id, []).append({
            "intent_id": item.get("intent_id"),
            "state": item.get("state"),
            "program_status": item.get("program_status"),
            "blocks_completion": item.get("blocks_completion") is True,
            "integrity_error": _truncate(str(item.get("integrity_error") or ""), 180) or None,
        })
    attempt_integrity_by_node: dict[str, list[dict[str, Any]]] = {}
    for finding in calculation_attempt_integrity_findings:
        for node_id in _string_list(finding.get("node_refs")):
            attempt_integrity_by_node.setdefault(node_id, []).append({
                "scope": finding.get("scope") or "attempt",
                "path": finding.get("path"),
                "intent_id": finding.get("intent_id"),
                "message": _truncate(str(finding.get("message") or ""), 180),
            })
    trajectory_by_node = {
        str(item.get("node_id")): item
        for item in trajectory.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
    }
    phase_rows = []
    for phase in selected["research_phases"]:
        phase_id = str(phase["phase_id"])
        phase_nodes = [node for node in nodes if node.get("phase_ref") == phase_id]
        phase_rows.append({
            "phase_id": phase_id,
            "title": phase["title"],
            "objective": _truncate(str(phase["objective"]), 180),
            "node_count": len(phase_nodes),
            "open_node_count": sum(node.get("status") == "open" for node in phase_nodes),
        })
    return {
        "schema_version": "ts-workspace-brief/1",
        "phases": phase_rows,
        "nodes": [
            {
                "node_id": node["node_id"],
                "phase_ref": node["phase_ref"],
                "title": node["title"],
                "status": node["status"],
                "objective": _truncate(str(node["objective"]), 240),
                "deliverable": _truncate(str(node["deliverable"]), 240),
                "contract_digest": node_contract_digest(node),
                "primary_claim_ref": node.get("primary_claim_ref"),
                "claim_refs": list(node.get("related_claim_refs", node.get("claim_refs", []))),
                "dependency_refs": list(node.get("dependency_refs", [])),
                "dependent_refs": list(trajectory_by_node.get(str(node["node_id"]), {}).get("dependent_refs", [])),
                "decision_rationale": _truncate(
                    str(
                        (trajectory_by_node.get(str(node["node_id"]), {}).get("opening_decision") or {}).get("rationale")
                        or ""
                    ),
                    280,
                ) or None,
                "result_summary": _truncate(str((node.get("result") or {}).get("summary") or ""), 240) or None,
                "activity": activity_by_node.get(str(node["node_id"])),
                "attempts": attempts_by_node.get(str(node["node_id"]), [])[:MAX_BRIEF_ATTEMPTS_PER_NODE],
                "attempt_integrity_findings": attempt_integrity_by_node.get(str(node["node_id"]), []),
            }
            for node in nodes
        ],
        "claims": [
            {
                "claim_id": claim["claim_id"],
                "status": claim["status"],
                "statement": _truncate(str(claim["statement"]), 320),
                "current_acceptance": claim["claim_id"] in current_claims,
                "observation_count": len(claim.get("observation_refs", [])),
                "validation_result_count": len(claim.get("validation_result_refs", [])),
            }
            for claim in claims
        ],
        "open_findings": [
            {
                "finding_id": finding["finding_id"],
                "severity": finding["severity"],
                "statement": _truncate(str(finding["statement"]), 240),
                "claim_refs": list(finding.get("claim_refs", [])),
                "node_refs": list(finding.get("node_refs", [])),
            }
            for finding in findings
            if finding.get("status") == "open"
        ],
        "incomplete_proof": _incomplete_proof(
            selected["proof_specs"],
            selected["validation_results"],
        ),
    }


def _compact_calculation_attempts(
    rows: Any,
    selected_node_ids: set[str],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Keep lifecycle visibility useful without copying full Attempt records."""

    if not isinstance(rows, list):
        return [], 0
    selected = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("node_id") in selected_node_ids
        and isinstance(row.get("intent_id"), str)
    ]
    selected.sort(
        key=lambda row: (
            str(row.get("node_id") or ""),
            _attempt_ordinal(str(row.get("intent_id") or "")),
            str(row.get("intent_id") or ""),
        )
    )
    compact = [
        {
            "node_id": row.get("node_id"),
            "intent_id": row.get("intent_id"),
            "path": row.get("path"),
            "state": row.get("state") or "unknown",
            "program_status": row.get("program_status") or "not_run",
            "job_id": row.get("job_id"),
            "terminal": row.get("terminal") is True,
            "blocks_completion": row.get("blocks_completion") is True,
            "integrity_error": _truncate(str(row.get("integrity_error") or ""), 240) or None,
        }
        for row in selected[:max(0, limit)]
    ]
    return compact, max(0, len(selected) - len(compact))


def _compact_attempt_integrity_findings(
    rows: Any,
    selected_node_ids: set[str],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Bound Attempt diagnostics while preserving parent scope explicitly."""

    if not isinstance(rows, list):
        return [], 0
    selected = [
        row
        for row in rows
        if isinstance(row, dict)
        and bool(set(_string_list(row.get("node_refs"))).intersection(selected_node_ids))
    ]
    selected.sort(
        key=lambda row: (
            str(row.get("path") or ""),
            str(row.get("message") or ""),
        )
    )
    compact = [
        {
            "code": row.get("code") or "calculation_attempt_integrity",
            "scope": row.get("scope") or "attempt",
            "path": row.get("path"),
            "node_refs": _string_list(row.get("node_refs")),
            "intent_id": row.get("intent_id"),
            "message": _truncate(str(row.get("message") or ""), 240),
        }
        for row in selected[:max(0, limit)]
    ]
    return compact, max(0, len(selected) - len(compact))


def _compact_operational_integrity_findings(
    rows: Any,
    selected_node_ids: set[str],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Bound path-integrity diagnostics before they enter Root context."""

    if not isinstance(rows, list):
        return [], 0
    selected = [
        row
        for row in rows
        if isinstance(row, dict)
        and (
            not selected_node_ids
            or bool(set(_string_list(row.get("node_refs"))).intersection(selected_node_ids))
        )
    ]
    selected.sort(
        key=lambda row: (
            str(row.get("path") or ""),
            str(row.get("message") or ""),
        )
    )
    compact = [
        {
            "code": row.get("code") or "operational_path_integrity",
            "path": row.get("path"),
            "node_refs": _string_list(row.get("node_refs")),
            "message": _truncate(str(row.get("message") or ""), 240),
        }
        for row in selected[:max(0, limit)]
    ]
    return compact, max(0, len(selected) - len(compact))


def _scientific_workspace_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Remove operational overlays before hashing a scientific context.

    The user-facing brief deliberately co-locates live activity and Attempt
    status with each Node.  Those fields are useful for navigation, but they
    are not canonical science and must not become part of ``projection_id``.
    Keep this boundary explicit so adding another operational overlay cannot
    accidentally alter Decision freshness semantics.
    """

    return {
        key: (
            [
                {
                    nested_key: nested_value
                    for nested_key, nested_value in node.items()
                    if nested_key not in {"activity", "attempts", "attempt_integrity_findings"}
                }
                for node in value
                if isinstance(node, dict)
            ]
            if key == "nodes" and isinstance(value, list)
            else value
        )
        for key, value in brief.items()
    }


def _attempt_ordinal(value: str) -> int:
    if value.startswith("calc_") and value.removeprefix("calc_").isdigit():
        return int(value.removeprefix("calc_"))
    return 2**63 - 1


def _truncate(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= maximum:
        return normalized
    return normalized[: maximum - 1].rstrip() + "..."


def _retrieval_hints(mode: str, selected: dict[str, list[dict[str, Any]]], omitted: dict[str, int]) -> dict[str, Any]:
    refs = {
        "claim": [str(item["claim_id"]) for item in selected["claims"][:8]],
        "node": [str(item["node_id"]) for item in selected["research_nodes"][:8]],
        "finding": [str(item["finding_id"]) for item in selected["findings"][:8]],
        "proof": [str(item["proof_id"]) for item in selected["proof_specs"][:8]],
    }
    return {
        "next_modes": [value for value in ("claim", "node", "finding", "proof", "subgraph") if value != mode],
        "visible_refs": refs,
        "has_more": any(value > 0 for value in omitted.values()),
    }


def _projection_id(value: Any) -> str:
    return "ctx_" + sha256_json(value).removeprefix("sha256:")[:24]


def _map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows if isinstance(row, dict) and isinstance(row.get(key), str)}


def _string_list(value: Any) -> list[str]:
    """Return only string members from a projected reference list."""

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
