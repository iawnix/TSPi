"""Revalidate analysis-owned candidates before the existing promotion path."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ts_agent.io import read_json, sha256_json
from ts_agent.reaction.mapping import mapping_finding_candidates, validate_atom_mapping

from .artifacts import WorkspaceArtifactError, resolve_workspace_artifact_ids
from .candidates import FindingCandidateError
from ts_agent.path_safety import has_symlink_component, lexical_path, path_has_symlink


def load_analysis_candidate(
    root: str | Path, artifact: dict[str, Any], node_id: str, candidate_id: str,
) -> dict[str, Any]:
    workspace = lexical_path(root)
    path = workspace / artifact["path"]
    if path_has_symlink(workspace) or has_symlink_component(workspace, path):
        raise FindingCandidateError("analysis candidate uses a symbolic link")
    if artifact["owner_node"] != node_id or path.stat().st_size > 4 * 1024 * 1024:
        raise FindingCandidateError("analysis candidate owner or size is invalid")
    try:
        document = read_json(path)
        if document.get("schema_version") == "ts-scientific-analysis/1":
            return _load_scientific_candidate(workspace, artifact, node_id, candidate_id, document)
        if (
            document.get("schema_version") != "ts-reaction-mapping-validation/1"
            or document.get("node_id") != node_id
            or document.get("capability") != "reaction.mapping.validate"
            or document.get("capability_version") != "1"
            or document.get("operation") != "validate"
        ):
            raise ValueError("unsupported analysis candidate producer binding")
        inputs = document["inputs"]
        if set(inputs) != {"reactants", "products"}:
            raise ValueError("analysis input roles changed")
        source_ids = []
        for side in ("reactants", "products"):
            if not isinstance(inputs[side], list) or not 1 <= len(inputs[side]) <= 64:
                raise ValueError("analysis input species limit exceeded")
            source_ids.extend(item["artifact_id"] for item in inputs[side])
        sources = resolve_workspace_artifact_ids(root, list(dict.fromkeys(source_ids)))
        by_id = {item["artifact_id"]: item for item in sources}
        # Recompute from the bound inputs, so editing a candidate and resolving
        # its new digest cannot promote an invented value as a measured fact.
        from ts_agent.structures.internals import read_xyz

        atoms = {}
        for side in ("reactants", "products"):
            atoms[side] = []
            for binding in inputs[side]:
                current = by_id[binding["artifact_id"]]
                if binding["artifact_ref"] != current["path"] or binding["sha256"] != current["sha256"]:
                    raise ValueError("analysis source artifact binding changed")
                if Path(current["path"]).suffix.lower() != ".xyz":
                    raise ValueError("analysis source must be XYZ")
                symbols, _ = read_xyz(workspace / current["path"])
                atoms[side].append(list(symbols))
            if sum(map(len, atoms[side])) > 4096:
                raise ValueError("analysis input atom limit exceeded")
        mapping = document["mapping"]
        if not isinstance(mapping, list) or len(mapping) > 4096:
            raise ValueError("analysis mapping limit exceeded")
        validation = validate_atom_mapping(atoms["reactants"], atoms["products"], mapping)
        expected = mapping_finding_candidates(validation, node_id, sources)
        if sha256_json(document["finding_candidates"]) != sha256_json(expected):
            raise ValueError("analysis candidate differs from recomputed source evidence")
        for field in ("valid", "complete", "verdict", "mapping_count", "pairs", "unmapped", "element_counts", "diagnostics"):
            if sha256_json(document[field]) != sha256_json(validation[field]):
                raise ValueError(f"analysis result {field} differs from recomputed source evidence")
        if document["atom_counts"] != {
            "reactants": validation["reactant_atom_count"], "products": validation["product_atom_count"],
        }:
            raise ValueError("analysis atom counts changed")
        if document["provenance"] != {
            "producer": expected["parser"]["name"], "producer_version": "1",
            "input_digests": [by_id[item]["sha256"] for item in source_ids],
        }:
            raise ValueError("analysis provenance binding changed")
        matches = [item for item in expected["candidates"] if item["candidate_id"] == candidate_id]
        if len(matches) != 1:
            raise ValueError(f"unknown analysis candidate: {candidate_id}")
        return {
            "document": expected, "candidate": deepcopy(matches[0]),
            "candidate_artifact": artifact, "source_artifacts": sources,
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, WorkspaceArtifactError) as exc:
        raise FindingCandidateError(f"invalid analysis candidate: {exc}") from exc


def _load_scientific_candidate(workspace, artifact, node_id, candidate_id, document):
    from jsonschema import Draft202012Validator
    from ts_agent.analysis.engine import load_inputs, evaluate, normalized_result, candidates, digest
    from ts_agent.analysis.catalog import DESCRIPTORS

    descriptor = next((item for item in DESCRIPTORS if item["capability"] == document["capability"] and item["version"] == document["capability_version"]), None)
    if descriptor is None or document["node_id"] != node_id:
        raise ValueError("analysis producer or owner is invalid")
    for field, schema in (("input_artifacts", "input_schema"), ("parameters", "parameter_schema")):
        error = next(Draft202012Validator(descriptor[schema]).iter_errors(document[field]), None)
        if error:
            raise ValueError(f"invalid analysis {field}: {error.message}")
    inputs, sources = load_inputs(workspace, document["input_artifacts"])
    bindings = {s["artifact_id"]: {k: s[k] for k in ("artifact_id", "path", "sha256")} for s in sources}
    recorded = document["source_artifacts"]
    recorded_by_id = {s["artifact_id"]: s for s in recorded}
    if len(recorded_by_id) != len(recorded) or sha256_json(bindings) != sha256_json(recorded_by_id):
        raise ValueError("analysis source artifact binding changed")
    # JSON key ordering must not alter source identity. Preserve the original
    # source order when replaying candidates written before canonical ordering.
    sources_by_id = {s["artifact_id"]: s for s in sources}
    sources = [sources_by_id[s["artifact_id"]] for s in recorded]
    result = evaluate(document["capability"], inputs, document["parameters"])
    expected = candidates(document["capability"], node_id, result, sources)
    if sha256_json(document["result"]) != sha256_json(normalized_result(result)) or sha256_json(document["finding_candidates"]) != sha256_json(expected):
        raise ValueError("analysis candidate differs from recomputed source evidence")
    generated = document["output_artifacts"]
    if set(generated) != set(result["files"]):
        raise ValueError("analysis generated output roles changed")
    records = resolve_workspace_artifact_ids(workspace, [r["artifact_id"] for r in generated.values()]) if generated else []
    by_id = {r["artifact_id"]: r for r in records}
    for name, binding in generated.items():
        current = by_id[binding["artifact_id"]]
        if current["owner_node"] != node_id or current["path"] != binding["path"] or current["sha256"] != digest(result["files"][name].encode()) or binding["sha256"] != current["sha256"]:
            raise ValueError("analysis generated output binding changed")
    matches = [r for r in expected["candidates"] if r["candidate_id"] == candidate_id]
    if len(matches) != 1:
        raise ValueError(f"unknown analysis candidate: {candidate_id}")
    return {"document": expected, "candidate": deepcopy(matches[0]), "candidate_artifact": artifact, "source_artifacts": sources}
