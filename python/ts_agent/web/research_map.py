"""Human-facing, read-only projection of Phases, hypotheses, and connectivity."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ts_agent.workspace.associations import derive_claim_node_links
from ts_agent.workspace.refs import (
    claim_relation_sort_key,
    claim_sort_key,
    node_sort_key,
    observation_sort_key,
    phase_sort_key,
)


ENDPOINT_ASSIGNMENT = "reaction_path.endpoint_assignment"
_DIRECTION_FIELD = "connectivity_direction"
_DIRECTED_VALUES = {"forward_to_reverse", "reverse_to_forward"}


def project_research_map(
    phases: Iterable[dict[str, Any]],
    nodes: Iterable[dict[str, Any]],
    claims: Iterable[dict[str, Any]],
    claim_relations: Iterable[dict[str, Any]],
    observations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Group ResearchNodes by Phase and Claim without changing canonical state."""

    phase_rows = _sorted_records(phases, "phase_id", phase_sort_key)
    node_rows = _sorted_records(nodes, "node_id", node_sort_key)
    claim_rows = _sorted_records(claims, "claim_id", claim_sort_key)
    relation_rows = _sorted_records(claim_relations, "relation_id", claim_relation_sort_key)
    observation_rows = _sorted_records(observations, "observation_id", observation_sort_key)
    claim_by_id = {
        str(row["claim_id"]): row
        for row in claim_rows
        if isinstance(row.get("claim_id"), str)
    }
    node_by_id = {
        str(row["node_id"]): row
        for row in node_rows
        if isinstance(row.get("node_id"), str)
    }
    related_by_node: dict[str, list[str]] = defaultdict(list)
    for claim_ref, node_ref in derive_claim_node_links(claim_rows, node_rows):
        related_by_node[node_ref].append(claim_ref)
    connectivity = _connectivity_segments(observation_rows, node_by_id)
    connectivity_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for segment in connectivity:
        connectivity_by_node[str(segment["node_ref"])].append(segment)

    projected_nodes = [
        _project_node(node, node_by_id)
        for node in node_rows
        if isinstance(node.get("node_id"), str)
    ]
    projected_phases = [
        _project_phase(
            phase,
            node_rows,
            claim_by_id,
            relation_rows,
            related_by_node,
            connectivity_by_node,
        )
        for phase in phase_rows
    ]
    return {
        "schema_version": "ts-research-map/1",
        "phases": projected_phases,
        "nodes": projected_nodes,
        "connectivity_segments": connectivity,
        "summary": {
            "phase_count": len(projected_phases),
            "lane_count": sum(len(row["lanes"]) for row in projected_phases),
            "shared_node_count": sum(len(row["shared_node_refs"]) for row in projected_phases),
            "connectivity_segment_count": len(connectivity),
        },
    }


def _project_phase(
    phase: dict[str, Any],
    nodes: list[dict[str, Any]],
    claim_by_id: dict[str, dict[str, Any]],
    relations: list[dict[str, Any]],
    related_by_node: dict[str, list[str]],
    connectivity_by_node: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    phase_id = str(phase.get("phase_id") or "")
    phase_nodes = [row for row in nodes if row.get("phase_ref") == phase_id]
    shared_refs = [
        str(row["node_id"])
        for row in phase_nodes
        if not _strings(row.get("dependency_refs"))
        and len(related_by_node.get(str(row.get("node_id") or ""), [])) > 1
    ]
    shared = set(shared_refs)
    assigned: dict[str, list[str]] = defaultdict(list)
    unassigned: list[str] = []
    phase_claims = {
        claim_ref
        for row in phase_nodes
        for claim_ref in related_by_node.get(str(row.get("node_id") or ""), [])
        if claim_ref in claim_by_id
    }
    for node in phase_nodes:
        node_ref = str(node.get("node_id") or "")
        if node_ref in shared:
            continue
        related = [ref for ref in related_by_node.get(node_ref, []) if ref in claim_by_id]
        primary = node.get("primary_claim_ref")
        if isinstance(primary, str) and primary in claim_by_id:
            assigned[primary].append(node_ref)
            phase_claims.add(primary)
        elif len(related) == 1:
            assigned[related[0]].append(node_ref)
        else:
            unassigned.append(node_ref)

    lanes = [
        _claim_lane(claim_by_id[claim_ref], assigned.get(claim_ref, []), connectivity_by_node)
        for claim_ref in sorted(phase_claims, key=claim_sort_key)
    ]
    if unassigned:
        lanes.append(
            {
                "lane_id": "exploration",
                "lane_type": "exploration",
                "claim_ref": None,
                "claim_type": None,
                "statement": "Research not assigned to one hypothesis.",
                "status": "open",
                "node_refs": unassigned,
                "connectivity_segments": _segments_for_nodes(unassigned, connectivity_by_node),
            }
        )
    phase_relation_rows = [
        {
            "relation_ref": row.get("relation_id"),
            "source_claim_ref": row.get("source_claim_ref"),
            "target_claim_ref": row.get("target_claim_ref"),
            "relation_type": row.get("relation_type"),
            "rationale": row.get("rationale"),
        }
        for row in relations
        if row.get("source_claim_ref") in phase_claims
        and row.get("target_claim_ref") in phase_claims
    ]
    return {
        "phase_id": phase.get("phase_id"),
        "title": phase.get("title"),
        "objective": phase.get("objective"),
        "shared_node_refs": shared_refs,
        "shared_connectivity_segments": _segments_for_nodes(shared_refs, connectivity_by_node),
        "lanes": lanes,
        "claim_relations": phase_relation_rows,
    }


def _claim_lane(
    claim: dict[str, Any],
    node_refs: list[str],
    connectivity_by_node: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    claim_ref = str(claim.get("claim_id") or "")
    return {
        "lane_id": claim_ref,
        "lane_type": "claim",
        "claim_ref": claim_ref,
        "claim_type": claim.get("claim_type"),
        "statement": claim.get("statement"),
        "status": claim.get("status"),
        "node_refs": node_refs,
        "connectivity_segments": _segments_for_nodes(node_refs, connectivity_by_node),
    }


def _project_node(node: dict[str, Any], node_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    attempts = _objects(node.get("attempts"))
    latest = attempts[-1] if attempts else None
    dependencies = []
    for dependency_ref in _strings(node.get("dependency_refs")):
        dependency = node_by_id.get(dependency_ref)
        if dependency is None:
            continue
        observation_refs = _strings(dependency.get("observation_refs"))
        dependencies.append(
            {
                "node_ref": dependency_ref,
                "title": dependency.get("title"),
                "status": dependency.get("status"),
                "observation_refs": observation_refs,
                "observation_count": len(observation_refs),
            }
        )
    return {
        "node_ref": node.get("node_id"),
        "title": node.get("title"),
        "objective": node.get("objective"),
        "status": node.get("status"),
        "dependency_refs": _strings(node.get("dependency_refs")),
        "upstream_dependencies": dependencies,
        "attempt_count": len(attempts),
        "observation_candidate_count": sum(
            int(_object(attempt.get("observation_candidates")).get("candidate_count") or 0)
            for attempt in attempts
        ),
        "pending_observation_candidate_count": sum(
            int(_object(attempt.get("observation_candidates")).get("pending_count") or 0)
            for attempt in attempts
        ),
        "latest_calculation": (
            {
                "intent_id": latest.get("intent_id"),
                "capability": latest.get("capability"),
                "capability_version": latest.get("capability_version"),
                "expected_output_roles": _strings(latest.get("expected_output_roles")),
                "state": latest.get("display_state"),
                "program_status": latest.get("program_status"),
                "observation_candidates": _object(latest.get("observation_candidates")).get("status"),
            }
            if latest is not None
            else None
        ),
    }


def _connectivity_segments(
    observations: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    paired: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"forward": [], "reverse": []}
    )
    for observation in observations:
        if observation.get("concept_id") != ENDPOINT_ASSIGNMENT:
            continue
        node_ref = observation.get("created_by_node")
        subject_ref = observation.get("subject_ref")
        if not isinstance(node_ref, str) or node_ref not in node_by_id or not isinstance(subject_ref, str):
            continue
        value = observation.get("value")
        qualifiers = observation.get("qualifiers") if isinstance(observation.get("qualifiers"), dict) else {}
        if isinstance(value, dict):
            forward = value.get("forward")
            reverse = value.get("reverse")
            if _endpoint(forward) and _endpoint(reverse):
                candidates.append(_segment_candidate(observation, str(forward), str(reverse)))
            continue
        direction = qualifiers.get("direction")
        if direction not in {"forward", "reverse"} or not _endpoint(value):
            continue
        grouping_qualifiers = {key: item for key, item in qualifiers.items() if key != "direction"}
        group_key = (node_ref, subject_ref, json.dumps(grouping_qualifiers, sort_keys=True, separators=(",", ":")))
        paired[group_key][str(direction)].append(observation)

    for rows in paired.values():
        forward_values = {str(row["value"]) for row in rows["forward"]}
        reverse_values = {str(row["value"]) for row in rows["reverse"]}
        if len(forward_values) != 1 or len(reverse_values) != 1:
            continue
        source_rows = sorted(
            [*rows["forward"], *rows["reverse"]],
            key=lambda row: observation_sort_key(str(row.get("observation_id") or "")),
        )
        candidate = _segment_candidate(
            source_rows[0],
            next(iter(forward_values)),
            next(iter(reverse_values)),
        )
        candidate["observation_refs"] = [str(row["observation_id"]) for row in source_rows]
        candidates.append(candidate)

    merged: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (
            str(candidate["node_ref"]),
            str(candidate["subject_ref"]),
            str(candidate["endpoint_a"]),
            str(candidate["endpoint_b"]),
            str(candidate["direction"]),
        )
        if key not in merged:
            merged[key] = candidate
            continue
        merged[key]["observation_refs"] = sorted(
            set([*merged[key]["observation_refs"], *candidate["observation_refs"]]),
            key=observation_sort_key,
        )
    segments = list(merged.values())
    for segment in segments:
        segment["segment_id"] = segment["observation_refs"][0]
        segment["evidence_count"] = len(segment["observation_refs"])
    return sorted(
        segments,
        key=lambda row: (
            node_sort_key(str(row.get("node_ref") or "")),
            observation_sort_key(str(row.get("segment_id") or "")),
        ),
    )


def _segment_candidate(
    observation: dict[str, Any],
    forward: str,
    reverse: str,
) -> dict[str, Any]:
    qualifiers = observation.get("qualifiers") if isinstance(observation.get("qualifiers"), dict) else {}
    value = observation.get("value") if isinstance(observation.get("value"), dict) else {}
    explicit_direction = value.get(_DIRECTION_FIELD, qualifiers.get(_DIRECTION_FIELD))
    direction = str(explicit_direction) if explicit_direction in _DIRECTED_VALUES else "undirected"
    if direction == "forward_to_reverse":
        endpoint_a, endpoint_b = forward, reverse
    elif direction == "reverse_to_forward":
        endpoint_a, endpoint_b = reverse, forward
    else:
        endpoint_a, endpoint_b = sorted((forward, reverse))
    return {
        "segment_id": None,
        "node_ref": observation.get("created_by_node"),
        "subject_ref": observation.get("subject_ref"),
        "endpoint_a": endpoint_a,
        "endpoint_b": endpoint_b,
        "direction": direction,
        "summary": observation.get("summary"),
        "observation_refs": [str(observation.get("observation_id"))],
        "evidence_count": 1,
    }


def _segments_for_nodes(
    node_refs: Iterable[str],
    connectivity_by_node: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [segment for node_ref in node_refs for segment in connectivity_by_node.get(node_ref, [])]


def _endpoint(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sorted_records(
    values: Iterable[dict[str, Any]],
    key: str,
    sort_key: Any,
) -> list[dict[str, Any]]:
    return sorted(
        (dict(row) for row in values if isinstance(row, dict)),
        key=lambda row: sort_key(str(row.get(key) or "")),
    )


def _objects(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: Any) -> list[str]:
    return [row for row in value if isinstance(row, str)] if isinstance(value, list) else []
