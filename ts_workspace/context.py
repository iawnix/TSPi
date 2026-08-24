"""Revision-aware graph projections for Root, Review, UI, and reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ts_validation.registry import (
    RegistryError,
    builtin_predicate_registry,
    list_acceptance_profiles,
    list_gate_templates,
    load_gate_template,
)

from .acceptance import project_acceptances
from .associations import derive_claim_node_links
from .io import read_json, sha256_json
from .operational import operational_snapshot
from .refs import (
    acceptance_sort_key,
    node_sort_key,
    claim_relation_sort_key,
    claim_sort_key,
    finding_sort_key,
    observation_sort_key,
    phase_sort_key,
    validation_result_sort_key,
    validation_spec_sort_key,
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
    VALIDATION_SPECS_FILE,
    WORKSPACE_FILE,
)
from .validator import validate_workspace


CONTEXT_MODES = frozenset({"frontier", "claim", "node", "subgraph", "finding", "validation", "delta"})
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


class ContextCompileError(ValueError):
    """Raised when a graph projection request is invalid."""


def compile_context(
    root: str | Path,
    *,
    mode: str = "frontier",
    claim_ref: str | None = None,
    node_ref: str | None = None,
    finding_ref: str | None = None,
    validation_ref: str | None = None,
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
    root_path = Path(root).expanduser().resolve()
    documents = {name: read_json(root_path / name) for name in STATE_FILES}
    revision = workspace_revision_from_documents(documents)
    operations = operational_snapshot(root_path)

    if mode == "delta" and since_revision == revision and since_operational_revision == operations["operational_revision"]:
        return {
            "schema_version": "ts-context-projection/2",
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
        validation_ref=validation_ref,
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
        current_acceptances=all_acceptances,
    )
    payload = {
        "schema_version": "ts-context-projection/2",
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
        "incomplete_validation": _incomplete_validation(bounded["validation_specs"], bounded["validation_results"]),
        "unresolved_controls": operations["unresolved_controls"],
        "pending_review_dispositions": operations["pending_review_dispositions"],
        "activity_summaries": activity_summaries,
        "operational_summary": operations["operational_summary"],
        "recent_decisions": recent_decisions,
        "omitted": omitted,
        "retrieval": _retrieval_hints(mode, bounded, omitted),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    scientific_binding = {
        key: payload[key]
        for key in (
            "mode",
            "workspace_revision",
            "focus",
            "acceptance_summary",
            "workspace_brief",
            "research_phases",
            "claims",
            "claim_relations",
            "research_nodes",
            "observations",
            "validation_specs",
            "validation_results",
            "findings",
            "acceptances",
            "recent_decisions",
            "omitted",
        )
    }
    payload["projection_id"] = _projection_id(scientific_binding)
    return payload


def validation_capabilities(
    *,
    template_id: str | None = None,
    template_version: str | None = None,
) -> dict[str, Any]:
    if (template_id is None) != (template_version is None):
        raise ContextCompileError("focused validation capabilities require template_id and template_version together")
    registry = builtin_predicate_registry()
    payload = {
        "schema_version": "ts-validation-capabilities/2",
        "predicates": registry.capabilities,
        "predicate_registry_digest": registry.digest,
        "templates": list_gate_templates(),
        "acceptance_profiles": list_acceptance_profiles(),
        "agent_supplied_executable_code": False,
    }
    if template_id is not None and template_version is not None:
        try:
            template = load_gate_template(template_id, template_version)
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
        "validation_spec_refs": sorted(
            (str(item["spec_id"]) for item in projection["validation_specs"]),
            key=validation_spec_sort_key,
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
        "validation_specs": projection["validation_specs"],
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
    validation_ref: str | None,
    claim_refs: list[str],
    node_refs: list[str],
    depth: int,
) -> dict[str, list[dict[str, Any]]]:
    phases = _map(documents[RESEARCH_PHASES_FILE]["phases"], "phase_id")
    claims = _map(documents[CLAIMS_FILE]["claims"], "claim_id")
    relations = _map(documents[CLAIM_RELATIONS_FILE]["relations"], "relation_id")
    nodes = _map(documents[RESEARCH_NODES_FILE]["nodes"], "node_id")
    observations = _map(documents[OBSERVATIONS_FILE]["observations"], "observation_id")
    specs = _map(documents[VALIDATION_SPECS_FILE]["specs"], "spec_id")
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
    elif mode == "validation":
        spec = specs.get(str(validation_ref))
        result = results.get(str(validation_ref))
        if spec is None and result is None:
            raise ContextCompileError(f"unknown validation ref: {validation_ref}")
        if result is not None:
            spec = specs.get(str(result.get("spec_ref")))
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
    selected_spec_refs = {str(spec["spec_id"]) for spec in selected_specs}
    selected_results = [result for result in results.values() if result.get("spec_ref") in selected_spec_refs]
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
        "validation_specs": sorted(
            selected_specs,
            key=lambda value: validation_spec_sort_key(str(value["spec_id"])),
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
        "validation_specs": "specs",
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


def _incomplete_validation(specs: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = {str(result.get("spec_ref")): result for result in results}
    return [
        {
            "spec_ref": spec["spec_id"],
            "target_claim_ref": spec["target_claim_ref"],
            "dimension": spec["dimension"],
            "latest_verdict": latest.get(str(spec["spec_id"]), {}).get("verdict", "not_evaluated"),
        }
        for spec in specs
        if latest.get(str(spec["spec_id"]), {}).get("verdict") != "pass"
    ]


def _workspace_brief(
    selected: dict[str, list[dict[str, Any]]],
    *,
    trajectory: dict[str, Any],
    activity_summaries: list[dict[str, Any]],
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
        "incomplete_validation": _incomplete_validation(
            selected["validation_specs"],
            selected["validation_results"],
        ),
    }


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
        "validation": [str(item["spec_id"]) for item in selected["validation_specs"][:8]],
    }
    return {
        "next_modes": [value for value in ("claim", "node", "finding", "validation", "subgraph") if value != mode],
        "visible_refs": refs,
        "has_more": any(value > 0 for value in omitted.values()),
    }


def _projection_id(value: Any) -> str:
    return "ctx_" + sha256_json(value).removeprefix("sha256:")[:24]


def _map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows if isinstance(row, dict) and isinstance(row.get(key), str)}
