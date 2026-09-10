"""Read-only research-object to filesystem locator projection.

The canonical Claim graph and ResearchNode DAG remain the source of scientific
meaning. This module joins those records to the injected calculation artifact
catalog so callers can find physical files without creating another index.
"""

from __future__ import annotations

import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .associations import derive_claim_node_links
from .errors import ContractError
from ts_agent.io import read_json
from .operational import calculation_attempt_index
from .path_safety import has_symlink_component, lexical_path, path_has_symlink
from .refs import CALCULATION_ID
from .revision import workspace_revision_from_documents
from .state import (
    CLAIMS_FILE,
    OBSERVATIONS_FILE,
    RESEARCH_NODES_FILE,
    STATE_FILES,
    WORKSPACE_FILE,
)


LOCATOR_SCHEMA_VERSION = "ts-workspace-locator/1"
MAX_QUERY_CHARS = 256
MAX_MATCHES = 8
EXACT_ARTIFACT_LIMIT = 32
SEARCH_ARTIFACT_LIMIT = 4
DIRECTORY_LIMIT = 8
ATTEMPT_LIMIT = 8
KIND_ORDER = {"claim": 0, "node": 1, "observation": 2, "attempt": 3, "artifact": 4}


@dataclass(frozen=True)
class _LocatorIndex:
    root: Path
    claims: dict[str, dict[str, Any]]
    nodes: dict[str, dict[str, Any]]
    observations: dict[str, dict[str, Any]]
    artifacts: dict[str, dict[str, Any]]
    attempts: dict[tuple[str, str], dict[str, Any]]
    claim_to_nodes: dict[str, set[str]]
    node_to_claims: dict[str, set[str]]
    observation_to_claims: dict[str, set[str]]
    artifact_to_observations: dict[str, set[str]]
    integrity_findings: list[dict[str, Any]]


def locate_research_files(
    root: str | Path,
    query: str,
    *,
    artifacts: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Locate bounded research records, directories, attempts, and artifacts.

    ``artifacts`` must come from the authoritative calculation artifact catalog.
    The function performs no writes and creates no durable locator state.
    """

    if not isinstance(query, str):
        raise ContractError("research file query must be a string")
    normalized_query = query.strip()
    if len(normalized_query) > MAX_QUERY_CHARS:
        raise ContractError(f"research file query exceeds {MAX_QUERY_CHARS} characters")

    root_path = lexical_path(root)
    if path_has_symlink(root_path):
        raise ContractError(f"workspace root contains a symbolic link: {root_path}")
    documents = _read_state_documents(root_path)
    if documents[WORKSPACE_FILE].get("schema_version") != "ts-workspace/6":
        raise ContractError(f"not an initialized TS workspace: {root_path}")
    index = _build_index(root_path, documents, artifacts)
    entities = _entities(index)
    exact = [item for item in entities if item["ref"].casefold() == normalized_query.casefold()]
    if normalized_query and exact:
        query_mode = "exact"
        terms: list[str] = []
        selected = exact
    elif normalized_query:
        query_mode = "search"
        terms = normalized_query.casefold().split()
        selected = [item for item in entities if _matches_terms(item["fields"], terms)]
    else:
        query_mode = "index"
        terms = []
        selected = [item for item in entities if item["kind"] in {"claim", "node"}]

    selected.sort(key=lambda item: _entity_sort_key(item, normalized_query))
    match_count = len(selected)
    omitted_matches = max(0, match_count - MAX_MATCHES)
    selected = selected[:MAX_MATCHES]
    artifact_limit = EXACT_ARTIFACT_LIMIT if query_mode == "exact" else SEARCH_ARTIFACT_LIMIT
    matches = [
        _project_match(
            item,
            index,
            artifact_limit=artifact_limit,
            matched_fields=_matched_fields(item["fields"], terms, query_mode),
        )
        for item in selected
    ]
    return {
        "schema_version": LOCATOR_SCHEMA_VERSION,
        "workspace_root": str(root_path),
        "workspace_revision": workspace_revision_from_documents(documents),
        "query": normalized_query,
        "query_mode": query_mode,
        "match_count": match_count,
        "returned_match_count": len(matches),
        "omitted_matches": omitted_matches,
        "integrity_findings": index.integrity_findings,
        "matches": matches,
    }


def _build_index(
    root: Path,
    documents: dict[str, dict[str, Any]],
    artifact_rows: Iterable[dict[str, Any]],
) -> _LocatorIndex:
    claims = _record_map(documents[CLAIMS_FILE].get("claims"), "claim_id")
    nodes = _record_map(documents[RESEARCH_NODES_FILE].get("nodes"), "node_id")
    observations = _record_map(documents[OBSERVATIONS_FILE].get("observations"), "observation_id")
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_rows = list(artifact_rows)
    for raw in artifact_rows:
        if not isinstance(raw, dict):
            raise ContractError("artifact catalog entries must be objects")
        artifact_id = raw.get("artifact_id")
        path = raw.get("path")
        if not isinstance(artifact_id, str) or not artifact_id or not isinstance(path, str) or not path:
            raise ContractError("artifact catalog entry is missing artifact_id or path")
        if artifact_id in artifacts:
            raise ContractError(f"artifact catalog contains duplicate artifact_id: {artifact_id}")
        artifacts[artifact_id] = dict(raw)

    claim_to_nodes = {claim_id: set() for claim_id in claims}
    node_to_claims = {node_id: set() for node_id in nodes}
    for claim_id, node_id in derive_claim_node_links(claims.values(), nodes.values()):
        claim_to_nodes[claim_id].add(node_id)
        node_to_claims[node_id].add(claim_id)

    observation_to_claims = {observation_id: set() for observation_id in observations}
    for claim_id, claim in claims.items():
        for observation_id in _strings(claim.get("observation_refs")):
            if observation_id in observation_to_claims:
                observation_to_claims[observation_id].add(claim_id)

    artifact_to_observations = {artifact_id: set() for artifact_id in artifacts}
    for observation_id, observation in observations.items():
        for artifact_id in _strings(observation.get("artifact_refs")):
            artifact_to_observations.setdefault(artifact_id, set()).add(observation_id)

    attempts, integrity_findings = _read_attempts(root, nodes, artifacts)
    return _LocatorIndex(
        root=root,
        claims=claims,
        nodes=nodes,
        observations=observations,
        artifacts=artifacts,
        attempts=attempts,
        claim_to_nodes=claim_to_nodes,
        node_to_claims=node_to_claims,
        observation_to_claims=observation_to_claims,
        artifact_to_observations=artifact_to_observations,
        integrity_findings=integrity_findings,
    )


def _entities(index: _LocatorIndex) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for claim_id, claim in index.claims.items():
        entities.append(
            _entity(
                "claim",
                claim_id,
                str(claim.get("statement") or claim_id),
                claim.get("status"),
                {
                    "ref": claim_id,
                    "statement": claim.get("statement"),
                    "type": claim.get("claim_type"),
                    "status": claim.get("status"),
                    "tags": claim.get("tags"),
                },
            )
        )
    for node_id, node in index.nodes.items():
        entities.append(
            _entity(
                "node",
                node_id,
                str(node.get("objective") or node_id),
                node.get("status"),
                {
                    "ref": node_id,
                    "phase": node.get("phase_ref"),
                    "title": node.get("title"),
                    "objective": node.get("objective"),
                    "deliverable": node.get("deliverable"),
                    "primary_claim": node.get("primary_claim_ref"),
                    "claims": node.get("claim_refs"),
                    "status": node.get("status"),
                    "tags": node.get("tags"),
                },
            )
        )
    for observation_id, observation in index.observations.items():
        entities.append(
            _entity(
                "observation",
                observation_id,
                str(observation.get("summary") or observation.get("concept_id") or observation_id),
                None,
                {
                    "ref": observation_id,
                    "concept": observation.get("concept_id"),
                    "subject": observation.get("subject_ref"),
                    "summary": observation.get("summary"),
                    "value": observation.get("value"),
                    "artifacts": observation.get("artifact_refs"),
                },
            )
        )
    for key, attempt in index.attempts.items():
        label = " ".join(
            value
            for value in (str(attempt.get("backend") or ""), str(attempt.get("task_type") or ""))
            if value
        ) or key[1]
        entities.append(
            {
                **_entity(
                    "attempt",
                    key[1],
                    label,
                    attempt.get("state"),
                    {
                        "ref": key[1],
                        "path": attempt.get("path"),
                        "node": key[0],
                        "backend": attempt.get("backend"),
                        "task": attempt.get("task_type"),
                        "state": attempt.get("state"),
                        "program_status": attempt.get("program_status"),
                        "error": attempt.get("error_class"),
                    },
                ),
                "key": key,
            }
        )
    for artifact_id, artifact in index.artifacts.items():
        entities.append(
            _entity(
                "artifact",
                artifact_id,
                str(artifact["path"]),
                None,
                {
                    "ref": artifact_id,
                    "path": artifact.get("path"),
                    "name": PurePosixPath(str(artifact.get("path"))).name,
                    "node": artifact.get("owner_node"),
                    "attempt": artifact.get("source_intent_id"),
                    "roles": artifact.get("input_roles"),
                },
            )
        )
    return entities


def _entity(
    kind: str,
    ref: str,
    label: str,
    status: Any,
    fields: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "ref": ref,
        "label": label,
        "status": status if isinstance(status, str) else None,
        "fields": {key: _search_text(value) for key, value in fields.items()},
    }


def _project_match(
    entity: dict[str, Any],
    index: _LocatorIndex,
    *,
    artifact_limit: int,
    matched_fields: list[str],
) -> dict[str, Any]:
    kind = str(entity["kind"])
    ref = str(entity["ref"])
    claim_refs: set[str] = set()
    node_refs: set[str] = set()
    observation_refs: set[str] = set()
    artifact_refs: set[str] = set()
    attempt_keys: set[tuple[str, str]] = set()

    if kind == "claim":
        claim_refs.add(ref)
        node_refs.update(index.claim_to_nodes.get(ref, set()))
        observation_refs.update(_strings(index.claims[ref].get("observation_refs")))
        artifact_refs.update(_observation_artifacts(index, observation_refs))
        attempt_keys.update(_artifact_attempts(index, artifact_refs))
    elif kind == "node":
        node_refs.add(ref)
        claim_refs.update(index.node_to_claims.get(ref, set()))
        observation_refs.update(_node_observations(index, ref))
        artifact_refs.update(
            artifact_id
            for artifact_id, artifact in index.artifacts.items()
            if artifact.get("owner_node") == ref
        )
        artifact_refs.update(_observation_artifacts(index, observation_refs))
        attempt_keys.update(key for key in index.attempts if key[0] == ref)
        artifact_refs.update(_attempt_artifacts(index, attempt_keys))
    elif kind == "observation":
        observation_refs.add(ref)
        observation = index.observations[ref]
        creator = observation.get("created_by_node")
        if isinstance(creator, str):
            node_refs.add(creator)
        claim_refs.update(index.observation_to_claims.get(ref, set()))
        artifact_refs.update(_strings(observation.get("artifact_refs")))
        attempt_keys.update(_artifact_attempts(index, artifact_refs))
    elif kind == "artifact":
        artifact_refs.add(ref)
        observation_refs.update(index.artifact_to_observations.get(ref, set()))
        claim_refs.update(_observation_claims(index, observation_refs))
        node_refs.update(_observation_acts(index, observation_refs))
        artifact = index.artifacts[ref]
        owner = artifact.get("owner_node")
        if isinstance(owner, str):
            node_refs.add(owner)
        attempt_keys.update(_artifact_attempts(index, artifact_refs))
        node_refs.update(key[0] for key in attempt_keys)
    elif kind == "attempt":
        key = entity["key"]
        attempt_keys.add(key)
        node_refs.add(key[0])
        artifact_refs.update(index.attempts[key]["artifact_ids"])
        observation_refs.update(_artifact_observations(index, artifact_refs))
        claim_refs.update(_observation_claims(index, observation_refs))
    else:  # pragma: no cover - all entity kinds are constructed above
        raise ContractError(f"unsupported locator entity kind: {kind}")

    available_artifact_refs = sorted(
        (artifact_id for artifact_id in artifact_refs if artifact_id in index.artifacts),
        key=lambda artifact_id: str(index.artifacts[artifact_id]["path"]),
    )
    unresolved_artifact_refs = sorted(artifact_refs - set(available_artifact_refs))
    projected_artifacts = [
        _project_artifact(
            index,
            artifact_id,
            kind=kind,
            selected_observations=observation_refs,
            selected_attempts=attempt_keys,
        )
        for artifact_id in available_artifact_refs[:artifact_limit]
    ]
    omitted_artifacts = max(0, len(available_artifact_refs) - artifact_limit)
    selected_attempts = sorted(attempt_keys, key=lambda key: (key[0], key[1]))
    directories = _directories(index, node_refs)
    return {
        "kind": kind,
        "ref": ref,
        "label": entity["label"],
        "status": entity["status"],
        "matched_fields": matched_fields,
        "claim_refs": _natural_refs(claim_refs),
        "node_refs": _natural_refs(node_refs),
        "observation_refs": _natural_refs(observation_refs),
        "directories": directories[:DIRECTORY_LIMIT],
        "omitted_directories": max(0, len(directories) - DIRECTORY_LIMIT),
        "attempts": [
            {
                name: value
                for name, value in index.attempts[key].items()
                if name not in {"artifact_ids", "input_artifact_ids", "output_artifact_ids"}
            }
            for key in selected_attempts[:ATTEMPT_LIMIT]
        ],
        "omitted_attempts": max(0, len(selected_attempts) - ATTEMPT_LIMIT),
        "artifacts": projected_artifacts,
        "unresolved_artifact_refs": unresolved_artifact_refs,
        "omitted_artifacts": omitted_artifacts,
    }


def _project_artifact(
    index: _LocatorIndex,
    artifact_id: str,
    *,
    kind: str,
    selected_observations: set[str],
    selected_attempts: set[tuple[str, str]],
) -> dict[str, Any]:
    artifact = index.artifacts[artifact_id]
    all_observation_refs = index.artifact_to_observations.get(artifact_id, set())
    selected_sources = all_observation_refs.intersection(selected_observations)
    observation_refs = all_observation_refs if kind == "artifact" else selected_sources
    attempt_direction = _attempt_artifact_direction(index, artifact_id, selected_attempts)
    concept_ids = {
        str(index.observations[observation_id]["concept_id"])
        for observation_id in observation_refs
        if observation_id in index.observations and index.observations[observation_id].get("concept_id")
    }
    if kind == "claim":
        relation = "direct_claim_evidence"
    elif kind == "observation":
        relation = "observation_source"
    elif kind == "attempt":
        relation = f"attempt_{attempt_direction}" if attempt_direction else "attempt_artifact"
    elif kind == "artifact":
        relation = "matched_artifact"
    elif selected_sources:
        relation = "node_observation_source"
    elif attempt_direction:
        relation = f"node_attempt_{attempt_direction}"
    else:
        relation = "node_owned"
    return {
        **artifact,
        "relation": relation,
        "observation_refs": _natural_refs(observation_refs),
        "claim_refs": _natural_refs(_observation_claims(index, observation_refs)),
        "concept_ids": sorted(concept_ids),
    }


def _directories(
    index: _LocatorIndex,
    node_refs: set[str],
) -> list[dict[str, Any]]:
    return [
        _directory(
            index.root,
            str(index.nodes.get(node_id, {}).get("artifact_root") or f"nodes/{node_id}"),
            "node_root",
        )
        for node_id in _natural_refs(node_refs)
    ]


def _directory(root: Path, path: str, purpose: str) -> dict[str, Any]:
    relative = _safe_relative_path(path)
    if relative is None:
        return {
            "path": path,
            "purpose": purpose,
            "exists": False,
            "integrity_error": "directory path is not workspace-relative",
        }
    candidate = root.joinpath(*relative.parts)
    result = {
        "path": path,
        "purpose": purpose,
        "exists": False,
    }
    if has_symlink_component(root, candidate):
        result["integrity_error"] = "directory path contains a symbolic-link component"
        return result
    try:
        result["exists"] = candidate.is_dir() and not candidate.is_symlink()
    except OSError as exc:
        result["integrity_error"] = f"cannot inspect directory: {exc}"
    return result


def _read_attempts(
    root: Path,
    nodes: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    """Project the shared lifecycle index and join it to artifact metadata.

    The operational kernel owns Attempt discovery, status interpretation, and
    fail-closed path checks.  The locator only adds navigation metadata (input
    and output artifact IDs); it never reinterprets a lifecycle document or
    follows a physical path that the kernel rejected.
    """

    attempts: dict[tuple[str, str], dict[str, Any]] = {}
    integrity_findings: list[dict[str, Any]] = []
    known_nodes = set(nodes)
    lifecycle_rows = calculation_attempt_index(root)
    integrity_findings.extend(_attempt_parent_integrity_findings(root, known_nodes))
    for lifecycle in lifecycle_rows:
        if not isinstance(lifecycle, dict):
            continue
        node_id = lifecycle.get("node_id")
        intent_id = lifecycle.get("intent_id")
        path_text = lifecycle.get("path")
        if not isinstance(node_id, str) or node_id not in known_nodes:
            continue
        if isinstance(lifecycle.get("integrity_error"), str) and lifecycle["integrity_error"]:
            integrity_findings.append({
                "code": "calculation_attempt_integrity",
                "path": str(path_text or f"nodes/{node_id}/attempts"),
                "node_refs": [node_id],
                "message": lifecycle["integrity_error"],
            })
        if not isinstance(intent_id, str) or CALCULATION_ID.fullmatch(intent_id) is None:
            # A parent-scope integrity row (for example a symlinked
            # ``attempts/`` directory) has no concrete Attempt entity, but its
            # diagnostic remains visible at the locator top level.
            continue
        relative = _safe_relative_path(path_text)
        if relative is None:
            integrity_findings.append({
                "code": "calculation_attempt_integrity",
                "path": str(path_text or intent_id),
                "node_refs": [node_id],
                "message": "Attempt path is not a workspace-relative path",
            })
            continue
        attempt_dir = root.joinpath(*relative.parts)
        unsafe = has_symlink_component(root, attempt_dir)
        intent = _read_optional_object(attempt_dir / "intent.json", root=root) if not unsafe else {}
        status = _read_optional_object(attempt_dir / "status.json", root=root) if not unsafe else {}
        result = (
            _read_optional_object(attempt_dir / "outputs" / "calculation_result.json", root=root)
            if not unsafe
            else {}
        )
        key = (node_id, intent_id)
        attempts[key] = {
            "intent_id": intent_id,
            "owner_node": node_id,
            "path": relative.as_posix(),
            "backend": intent.get("backend") or result.get("backend"),
            "task_type": intent.get("task_type") or result.get("task_type"),
            # State and integrity are authoritative in the shared lifecycle
            # row.  The local documents are only used for descriptive fields.
            "state": lifecycle.get("state"),
            "program_status": lifecycle.get("program_status"),
            "error_class": result.get("error_class") or status.get("error_class"),
            "input_artifact_ids": _input_artifact_ids(intent),
            "output_artifact_ids": [],
            "terminal": lifecycle.get("terminal") is True,
            "blocks_completion": lifecycle.get("blocks_completion") is True,
            "integrity_error": lifecycle.get("integrity_error"),
        }

    # A catalog row can outlive an Attempt directory (for example while a
    # recovery process is being inspected).  Keep that relationship visible,
    # but do not invent lifecycle state; the shared index remains authoritative.
    for artifact_id, artifact in artifacts.items():
        node_id = artifact.get("owner_node")
        intent_id = artifact.get("source_intent_id")
        if (
            not isinstance(node_id, str)
            or node_id not in known_nodes
            or not isinstance(intent_id, str)
            or CALCULATION_ID.fullmatch(intent_id) is None
        ):
            continue
        key = (node_id, intent_id)
        attempts.setdefault(
            key,
            {
                "intent_id": intent_id,
                "owner_node": node_id,
                "path": f"nodes/{node_id}/attempts/{intent_id}",
                "backend": None,
                "task_type": None,
                "state": None,
                "program_status": None,
                "error_class": None,
                "input_artifact_ids": [],
                "output_artifact_ids": [],
                "terminal": False,
                "blocks_completion": True,
                "integrity_error": "Attempt directory is missing from the lifecycle index",
            },
        )["output_artifact_ids"].append(artifact_id)
    for attempt in attempts.values():
        attempt["input_artifact_ids"] = _sorted_artifact_ids(
            attempt["input_artifact_ids"], artifacts
        )
        attempt["output_artifact_ids"] = _sorted_artifact_ids(
            attempt["output_artifact_ids"], artifacts
        )
        attempt["artifact_ids"] = _sorted_artifact_ids(
            [*attempt["input_artifact_ids"], *attempt["output_artifact_ids"]],
            artifacts,
        )
        attempt["input_artifact_count"] = len(attempt["input_artifact_ids"])
        attempt["output_artifact_count"] = len(attempt["output_artifact_ids"])
        attempt["artifact_count"] = len(attempt["artifact_ids"])
    integrity_findings = _unique_integrity_findings(integrity_findings)
    integrity_findings.sort(key=lambda row: (str(row.get("path") or ""), str(row.get("message") or "")))
    return attempts, integrity_findings


def _attempt_parent_integrity_findings(
    root: Path,
    node_ids: set[str],
) -> list[dict[str, Any]]:
    """Report an unsafe or unreadable ``attempts/`` parent even when empty."""

    findings: list[dict[str, Any]] = []
    for node_id in sorted(node_ids):
        parent = root / "nodes" / node_id / "attempts"
        try:
            mode = parent.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            findings.append({
                "code": "calculation_attempt_integrity",
                "path": parent.relative_to(root).as_posix(),
                "node_refs": [node_id],
                "message": f"cannot inspect Attempt parent: {exc}",
            })
            continue
        if stat.S_ISLNK(mode):
            findings.append({
                "code": "calculation_attempt_integrity",
                "path": parent.relative_to(root).as_posix(),
                "node_refs": [node_id],
                "message": "Attempt parent path contains a symbolic-link component",
            })
        elif not stat.S_ISDIR(mode):
            findings.append({
                "code": "calculation_attempt_integrity",
                "path": parent.relative_to(root).as_posix(),
                "node_refs": [node_id],
                "message": "Attempt parent path is not a directory",
            })
    return findings


def _unique_integrity_findings(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("path") or ""), str(row.get("message") or ""))
        unique.setdefault(key, row)
    return list(unique.values())


def _record_map(value: Any, key: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        raise ContractError(f"workspace registry field for {key} must be an array")
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            raise ContractError(f"workspace registry contains an invalid {key}")
        ref = str(item[key])
        if ref in records:
            raise ContractError(f"workspace registry contains duplicate {key}: {ref}")
        records[ref] = item
    return records


def _read_optional_object(path: Path, *, root: Path) -> dict[str, Any]:
    if has_symlink_component(root, path):
        return {}
    try:
        if not path.is_file() or path.is_symlink():
            return {}
    except OSError:
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_state_documents(root: Path) -> dict[str, dict[str, Any]]:
    """Read canonical locator inputs without crossing a symbolic link."""

    documents: dict[str, dict[str, Any]] = {}
    for name in STATE_FILES:
        path = root / name
        if has_symlink_component(root, path) or path.is_symlink():
            raise ContractError(f"workspace file contains a symbolic link: {name}")
        try:
            value = read_json(path)
        except (OSError, ValueError) as exc:
            raise ContractError(f"cannot read workspace file {name}: {exc}") from exc
        if not isinstance(value, dict):
            raise ContractError(f"workspace file is not an object: {name}")
        documents[name] = value
    return documents


def _safe_relative_path(value: Any) -> PurePosixPath | None:
    """Normalize a path supplied by a registry without allowing traversal."""

    if not isinstance(value, str) or not value:
        return None
    relative = PurePosixPath(value.replace("\\", "/"))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        return None
    return relative


def _input_artifact_ids(intent: dict[str, Any]) -> list[str]:
    bindings = intent.get("input_bindings")
    if not isinstance(bindings, list):
        return []
    return [
        str(binding["artifact_id"])
        for binding in bindings
        if isinstance(binding, dict)
        and isinstance(binding.get("artifact_id"), str)
        and binding["artifact_id"]
    ]


def _sorted_artifact_ids(
    artifact_ids: Iterable[str],
    artifacts: dict[str, dict[str, Any]],
) -> list[str]:
    return sorted(
        set(artifact_ids),
        key=lambda artifact_id: str(artifacts.get(artifact_id, {}).get("path") or artifact_id),
    )


def _node_observations(index: _LocatorIndex, node_id: str) -> set[str]:
    refs = set(_strings(index.nodes[node_id].get("observation_refs")))
    refs.update(
        observation_id
        for observation_id, observation in index.observations.items()
        if observation.get("created_by_node") == node_id
    )
    return refs


def _observation_artifacts(index: _LocatorIndex, observation_refs: Iterable[str]) -> set[str]:
    return {
        artifact_id
        for observation_id in observation_refs
        if observation_id in index.observations
        for artifact_id in _strings(index.observations[observation_id].get("artifact_refs"))
    }


def _artifact_observations(index: _LocatorIndex, artifact_refs: Iterable[str]) -> set[str]:
    return {
        observation_id
        for artifact_id in artifact_refs
        for observation_id in index.artifact_to_observations.get(artifact_id, set())
    }


def _observation_claims(index: _LocatorIndex, observation_refs: Iterable[str]) -> set[str]:
    return {
        claim_id
        for observation_id in observation_refs
        for claim_id in index.observation_to_claims.get(observation_id, set())
    }


def _observation_acts(index: _LocatorIndex, observation_refs: Iterable[str]) -> set[str]:
    return {
        str(index.observations[observation_id]["created_by_node"])
        for observation_id in observation_refs
        if observation_id in index.observations
        and isinstance(index.observations[observation_id].get("created_by_node"), str)
    }


def _artifact_attempts(
    index: _LocatorIndex,
    artifact_refs: Iterable[str],
) -> set[tuple[str, str]]:
    refs = set(artifact_refs)
    keys: set[tuple[str, str]] = set()
    for artifact_id in refs:
        artifact = index.artifacts.get(artifact_id)
        if artifact is None:
            continue
        node_id = artifact.get("owner_node")
        intent_id = artifact.get("source_intent_id")
        if isinstance(node_id, str) and isinstance(intent_id, str):
            keys.add((node_id, intent_id))
    keys.update(
        key
        for key, attempt in index.attempts.items()
        if refs.intersection(attempt["artifact_ids"])
    )
    return keys


def _attempt_artifacts(
    index: _LocatorIndex,
    attempt_keys: Iterable[tuple[str, str]],
) -> set[str]:
    return {
        artifact_id
        for key in attempt_keys
        if key in index.attempts
        for artifact_id in index.attempts[key]["artifact_ids"]
    }


def _attempt_artifact_direction(
    index: _LocatorIndex,
    artifact_id: str,
    attempt_keys: Iterable[tuple[str, str]],
) -> str | None:
    selected = [index.attempts[key] for key in attempt_keys if key in index.attempts]
    if any(artifact_id in attempt["input_artifact_ids"] for attempt in selected):
        return "input"
    if any(artifact_id in attempt["output_artifact_ids"] for attempt in selected):
        return "output"
    return None


def _matches_terms(fields: dict[str, str], terms: list[str]) -> bool:
    haystack = "\n".join(fields.values()).casefold()
    return bool(terms) and all(term in haystack for term in terms)


def _matched_fields(fields: dict[str, str], terms: list[str], query_mode: str) -> list[str]:
    if query_mode == "exact":
        return ["ref"]
    if query_mode == "index":
        return []
    return [
        name
        for name, value in fields.items()
        if any(term in value.casefold() for term in terms)
    ]


def _entity_sort_key(item: dict[str, Any], query: str) -> tuple[int, int, tuple[int, str]]:
    query_folded = query.casefold()
    ref = str(item["ref"])
    label = str(item["label"])
    if query_folded and ref.casefold().startswith(query_folded):
        score = 0
    elif query_folded and label.casefold().startswith(query_folded):
        score = 1
    else:
        score = 2
    return score, KIND_ORDER[str(item["kind"])], _natural_ref_key(ref)


def _natural_refs(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=_natural_ref_key)


def _natural_ref_key(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"(?:claim|node|obs)_([1-9][0-9]*)", value)
    return (int(match.group(1)), "") if match else (2**63 - 1, value)


def _search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
