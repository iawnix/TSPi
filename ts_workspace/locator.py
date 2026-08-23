"""Read-only research-object to filesystem locator projection.

The canonical Claim graph and ResearchAct DAG remain the source of scientific
meaning. This module joins those records to the injected calculation artifact
catalog so callers can find physical files without creating another index.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .associations import derive_claim_act_links
from .errors import ContractError
from .io import read_json
from .refs import CALCULATION_ID
from .revision import workspace_revision_from_documents
from .state import (
    CLAIMS_FILE,
    OBSERVATIONS_FILE,
    RESEARCH_ACTS_FILE,
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
KIND_ORDER = {"claim": 0, "act": 1, "observation": 2, "attempt": 3, "artifact": 4}


@dataclass(frozen=True)
class _LocatorIndex:
    root: Path
    claims: dict[str, dict[str, Any]]
    acts: dict[str, dict[str, Any]]
    observations: dict[str, dict[str, Any]]
    artifacts: dict[str, dict[str, Any]]
    attempts: dict[tuple[str, str], dict[str, Any]]
    claim_to_acts: dict[str, set[str]]
    act_to_claims: dict[str, set[str]]
    observation_to_claims: dict[str, set[str]]
    artifact_to_observations: dict[str, set[str]]


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

    root_path = Path(root).expanduser().resolve()
    documents = {name: read_json(root_path / name) for name in STATE_FILES}
    if documents[WORKSPACE_FILE].get("schema_version") != "ts-workspace/4":
        raise ContractError(f"not an initialized v4 TS workspace: {root_path}")
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
        selected = [item for item in entities if item["kind"] in {"claim", "act"}]

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
        "matches": matches,
    }


def _build_index(
    root: Path,
    documents: dict[str, dict[str, Any]],
    artifact_rows: Iterable[dict[str, Any]],
) -> _LocatorIndex:
    claims = _record_map(documents[CLAIMS_FILE].get("claims"), "claim_id")
    acts = _record_map(documents[RESEARCH_ACTS_FILE].get("acts"), "act_id")
    observations = _record_map(documents[OBSERVATIONS_FILE].get("observations"), "observation_id")
    artifacts: dict[str, dict[str, Any]] = {}
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

    claim_to_acts = {claim_id: set() for claim_id in claims}
    act_to_claims = {act_id: set() for act_id in acts}
    for claim_id, act_id in derive_claim_act_links(claims.values(), acts.values()):
        claim_to_acts[claim_id].add(act_id)
        act_to_claims[act_id].add(claim_id)

    observation_to_claims = {observation_id: set() for observation_id in observations}
    for claim_id, claim in claims.items():
        for observation_id in _strings(claim.get("observation_refs")):
            if observation_id in observation_to_claims:
                observation_to_claims[observation_id].add(claim_id)

    artifact_to_observations = {artifact_id: set() for artifact_id in artifacts}
    for observation_id, observation in observations.items():
        for artifact_id in _strings(observation.get("artifact_refs")):
            artifact_to_observations.setdefault(artifact_id, set()).add(observation_id)

    attempts = _read_attempts(root, acts, artifacts)
    return _LocatorIndex(
        root=root,
        claims=claims,
        acts=acts,
        observations=observations,
        artifacts=artifacts,
        attempts=attempts,
        claim_to_acts=claim_to_acts,
        act_to_claims=act_to_claims,
        observation_to_claims=observation_to_claims,
        artifact_to_observations=artifact_to_observations,
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
    for act_id, act in index.acts.items():
        hypothesis = act.get("hypothesis") if isinstance(act.get("hypothesis"), dict) else {}
        entities.append(
            _entity(
                "act",
                act_id,
                str(act.get("objective") or act_id),
                act.get("status"),
                {
                    "ref": act_id,
                    "objective": act.get("objective"),
                    "hypothesis": hypothesis,
                    "status": act.get("status"),
                    "tags": act.get("tags"),
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
                        "act": key[0],
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
                    "act": artifact.get("owner_act"),
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
    act_refs: set[str] = set()
    observation_refs: set[str] = set()
    artifact_refs: set[str] = set()
    attempt_keys: set[tuple[str, str]] = set()

    if kind == "claim":
        claim_refs.add(ref)
        act_refs.update(index.claim_to_acts.get(ref, set()))
        observation_refs.update(_strings(index.claims[ref].get("observation_refs")))
        artifact_refs.update(_observation_artifacts(index, observation_refs))
        attempt_keys.update(_artifact_attempts(index, artifact_refs))
    elif kind == "act":
        act_refs.add(ref)
        claim_refs.update(index.act_to_claims.get(ref, set()))
        observation_refs.update(_act_observations(index, ref))
        artifact_refs.update(
            artifact_id
            for artifact_id, artifact in index.artifacts.items()
            if artifact.get("owner_act") == ref
        )
        artifact_refs.update(_observation_artifacts(index, observation_refs))
        attempt_keys.update(key for key in index.attempts if key[0] == ref)
        artifact_refs.update(_attempt_artifacts(index, attempt_keys))
    elif kind == "observation":
        observation_refs.add(ref)
        observation = index.observations[ref]
        creator = observation.get("created_by_act")
        if isinstance(creator, str):
            act_refs.add(creator)
        claim_refs.update(index.observation_to_claims.get(ref, set()))
        artifact_refs.update(_strings(observation.get("artifact_refs")))
        attempt_keys.update(_artifact_attempts(index, artifact_refs))
    elif kind == "artifact":
        artifact_refs.add(ref)
        observation_refs.update(index.artifact_to_observations.get(ref, set()))
        claim_refs.update(_observation_claims(index, observation_refs))
        act_refs.update(_observation_acts(index, observation_refs))
        artifact = index.artifacts[ref]
        owner = artifact.get("owner_act")
        if isinstance(owner, str):
            act_refs.add(owner)
        attempt_keys.update(_artifact_attempts(index, artifact_refs))
        act_refs.update(key[0] for key in attempt_keys)
    elif kind == "attempt":
        key = entity["key"]
        attempt_keys.add(key)
        act_refs.add(key[0])
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
    directories = _directories(index, act_refs)
    return {
        "kind": kind,
        "ref": ref,
        "label": entity["label"],
        "status": entity["status"],
        "matched_fields": matched_fields,
        "claim_refs": _natural_refs(claim_refs),
        "act_refs": _natural_refs(act_refs),
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
        relation = "act_observation_source"
    elif attempt_direction:
        relation = f"act_attempt_{attempt_direction}"
    else:
        relation = "act_owned"
    return {
        **artifact,
        "relation": relation,
        "observation_refs": _natural_refs(observation_refs),
        "claim_refs": _natural_refs(_observation_claims(index, observation_refs)),
        "concept_ids": sorted(concept_ids),
    }


def _directories(
    index: _LocatorIndex,
    act_refs: set[str],
) -> list[dict[str, Any]]:
    return [
        _directory(
            index.root,
            str(index.acts.get(act_id, {}).get("artifact_root") or f"acts/{act_id}"),
            "act_root",
        )
        for act_id in _natural_refs(act_refs)
    ]


def _directory(root: Path, path: str, purpose: str) -> dict[str, Any]:
    candidate = root.joinpath(*PurePosixPath(path).parts)
    return {
        "path": path,
        "purpose": purpose,
        "exists": candidate.is_dir() and not candidate.is_symlink(),
    }


def _read_attempts(
    root: Path,
    acts: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    attempts: dict[tuple[str, str], dict[str, Any]] = {}
    for act_id in acts:
        attempts_root = root / "acts" / act_id / "attempts"
        if not attempts_root.is_dir() or attempts_root.is_symlink():
            continue
        for attempt_dir in sorted(attempts_root.iterdir()):
            if (
                not attempt_dir.is_dir()
                or attempt_dir.is_symlink()
                or CALCULATION_ID.fullmatch(attempt_dir.name) is None
            ):
                continue
            intent = _read_optional_object(attempt_dir / "intent.json")
            status = _read_optional_object(attempt_dir / "status.json")
            result = _read_optional_object(attempt_dir / "outputs" / "calculation_result.json")
            key = (act_id, attempt_dir.name)
            attempts[key] = {
                "intent_id": attempt_dir.name,
                "owner_act": act_id,
                "path": attempt_dir.relative_to(root).as_posix(),
                "backend": intent.get("backend") or result.get("backend"),
                "task_type": intent.get("task_type") or result.get("task_type"),
                "state": result.get("state") or status.get("state"),
                "program_status": result.get("program_status") or status.get("program_status"),
                "error_class": result.get("error_class") or status.get("error_class"),
                "input_artifact_ids": _input_artifact_ids(intent),
                "output_artifact_ids": [],
            }
    for artifact_id, artifact in artifacts.items():
        act_id = artifact.get("owner_act")
        intent_id = artifact.get("source_intent_id")
        if not isinstance(act_id, str) or not isinstance(intent_id, str):
            continue
        key = (act_id, intent_id)
        attempts.setdefault(
            key,
            {
                "intent_id": intent_id,
                "owner_act": act_id,
                "path": f"acts/{act_id}/attempts/{intent_id}",
                "backend": None,
                "task_type": None,
                "state": None,
                "program_status": None,
                "error_class": None,
                "input_artifact_ids": [],
                "output_artifact_ids": [],
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
    return attempts


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


def _read_optional_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


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


def _act_observations(index: _LocatorIndex, act_id: str) -> set[str]:
    refs = set(_strings(index.acts[act_id].get("observation_refs")))
    refs.update(
        observation_id
        for observation_id, observation in index.observations.items()
        if observation.get("created_by_act") == act_id
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
        str(index.observations[observation_id]["created_by_act"])
        for observation_id in observation_refs
        if observation_id in index.observations
        and isinstance(index.observations[observation_id].get("created_by_act"), str)
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
        act_id = artifact.get("owner_act")
        intent_id = artifact.get("source_intent_id")
        if isinstance(act_id, str) and isinstance(intent_id, str):
            keys.add((act_id, intent_id))
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
    match = re.fullmatch(r"(?:claim|act|obs)_([1-9][0-9]*)", value)
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
