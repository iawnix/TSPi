"""Parser-owned FindingCandidate records.

Candidates are deterministic parser output, not canonical scientific state.
They remain in an Attempt's parsed output directory until the Root Agent
explicitly promotes one through a ``research_change`` transaction.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from ts_agent.calculation_contracts import (
    CalculationContractError,
    validate_calculation_result_binding,
)
from ts_agent.io import read_json, sha256_json

from .artifacts import (
    WorkspaceArtifactError,
    resolve_workspace_artifact_ids,
)
from .errors import ContractError
from ts_agent.path_safety import has_symlink_component, lexical_path, path_has_symlink
from .schema_validation import SchemaValidationError, validate_contract


CANDIDATE_SCHEMA = "finding_candidates.schema.json"
CANDIDATE_SCHEMA_VERSION = "ts-finding-candidates/1"
CANDIDATE_FILE_NAME = "finding_candidates.json"
MAX_CANDIDATE_BYTES = 64 * 1024
_CANDIDATE_ID = re.compile(r"^candidate_[1-9][0-9]*$")
_CALCULATION_ID = re.compile(r"^calc_[1-9][0-9]*$")


class FindingCandidateError(ContractError):
    """Raised when a parser candidate cannot cross into canonical state."""


# Metadata and very large parser internals are not semantic candidates.  The
# parser's complete summary remains available in its backend summary artifact.
_SKIP_KEYS = frozenset({
    "log",
    "section_count",
    "selected_section_index",
    "selected_section_reason",
    "selected_section_start_line",
    "selected_section_end_line",
    "selected_frequency_table_index",
    "selected_frequency_table_reason",
    "selected_frequency_table_start_line",
    "selected_frequency_table_end_line",
    "frequency_table_count",
    "force_convergence",
})


def build_finding_candidates(
    *,
    intent: dict[str, Any],
    parser_result: dict[str, Any],
    parser_name: str,
    parser_contract: str,
    source_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert a parser summary into bounded, field-level candidates."""

    summary = parser_result.get("summary")
    if not isinstance(summary, dict):
        raise FindingCandidateError("parser result has no summary for FindingCandidates")
    sources = [_source_binding(item) for item in source_artifacts]
    candidates: list[dict[str, Any]] = []
    for key in sorted(summary):
        value = summary[key]
        if key in _SKIP_KEYS or value is None:
            continue
        if not _json_value(value):
            continue
        datatype = _datatype(value)
        concept_id = f"parser.{_concept_key(key)}"
        candidates.append(
            {
                "candidate_id": f"candidate_{len(candidates) + 1}",
                "concept_id": concept_id,
                "subject_ref": f"calculation:{intent['intent_id']}",
                "value": deepcopy(value),
                "datatype": datatype,
                "unit": _unit_for_key(key),
                "qualifiers": {
                    "capability": str(intent.get("capability") or ""),
                    "capability_version": str(intent.get("capability_version") or ""),
                    "parser_field": key,
                },
                "summary": f"Parser observed {key} for calculation {intent['intent_id']}.",
                "source_artifact_ids": [item["artifact_id"] for item in sources],
            }
        )
        if len(candidates) >= 128:
            break

    diagnostics: list[str] = []
    if not candidates:
        diagnostics.append("parser produced no non-null semantic candidate fields")
    document = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "intent_id": str(intent["intent_id"]),
        "node_id": str(intent["node_id"]),
        "capability": str(intent["capability"]),
        "capability_version": str(intent["capability_version"]),
        "parser": {"name": parser_name, "contract": parser_contract},
        "source_artifacts": sources,
        "candidates": candidates,
        "diagnostics": sorted(set(diagnostics))[:64],
    }
    truncated = False
    while _encoded_size(document) > MAX_CANDIDATE_BYTES and len(document["candidates"]) > 1:
        document["candidates"].pop()
        truncated = True
    if truncated:
        document["diagnostics"] = sorted(set([
            *document["diagnostics"],
            "candidate list truncated to the parser output size limit",
        ]))[:64]
    validate_finding_candidates(document)
    return document


def validate_finding_candidates(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FindingCandidateError("FindingCandidates must be an object")
    try:
        validate_contract(CANDIDATE_SCHEMA, value)
    except SchemaValidationError as exc:
        raise FindingCandidateError(str(exc)) from exc
    source_ids = [item["artifact_id"] for item in value["source_artifacts"]]
    if len(source_ids) != len(set(source_ids)):
        raise FindingCandidateError("FindingCandidates source_artifacts contain duplicate IDs")
    candidate_ids = [item["candidate_id"] for item in value["candidates"]]
    if candidate_ids != [f"candidate_{index}" for index in range(1, len(candidate_ids) + 1)]:
        raise FindingCandidateError("FindingCandidate IDs must be contiguous parser ordinals")
    for candidate in value["candidates"]:
        if candidate["source_artifact_ids"] != source_ids:
            raise FindingCandidateError(
                f"FindingCandidate {candidate['candidate_id']} source bindings differ from its document"
            )
        if not _datatype_matches(candidate["datatype"], candidate["value"]):
            raise FindingCandidateError(
                f"FindingCandidate {candidate['candidate_id']} datatype does not match its value"
            )
    if _encoded_size(value) > MAX_CANDIDATE_BYTES:
        raise FindingCandidateError(
            f"FindingCandidates exceed {MAX_CANDIDATE_BYTES} bytes"
        )
    return value


def load_finding_candidate(
    root: str | Path,
    *,
    node_id: str,
    artifact_id: str,
    artifact_sha256: str | None,
    candidate_id: str,
) -> dict[str, Any]:
    """Load and revalidate one parser candidate for canonical promotion."""

    if not _CANDIDATE_ID.fullmatch(candidate_id):
        raise FindingCandidateError(f"invalid FindingCandidate ID: {candidate_id}")
    try:
        artifact = resolve_workspace_artifact_ids(root, [artifact_id])[0]
    except (WorkspaceArtifactError, IndexError) as exc:
        raise FindingCandidateError(f"unknown FindingCandidate artifact: {artifact_id}") from exc
    if artifact_sha256 is not None and artifact["sha256"] != artifact_sha256:
        raise FindingCandidateError("FindingCandidate artifact digest changed")
    path = str(artifact["path"])
    parts = PurePosixPath(path).parts
    if len(parts) == 5 and parts[:4] == ("nodes", node_id, "outputs", "analysis"):
        from .analysis_candidates import load_analysis_candidate

        return load_analysis_candidate(root, artifact, node_id, candidate_id)
    if (
        len(parts) != 7
        or parts[0] != "nodes"
        or parts[1] != node_id
        or parts[2] != "attempts"
        or not _CALCULATION_ID.fullmatch(parts[3])
        or parts[4] != "outputs"
        or parts[5] != "parsed"
        or parts[6] != CANDIDATE_FILE_NAME
    ):
        raise FindingCandidateError("FindingCandidate artifact is outside an Attempt parsed output")
    workspace = lexical_path(root)
    if path_has_symlink(workspace):
        raise FindingCandidateError("FindingCandidate workspace root uses a symbolic link")
    candidate_file = workspace / path
    if has_symlink_component(workspace, candidate_file) or candidate_file.is_symlink():
        raise FindingCandidateError("FindingCandidate artifact uses a symbolic link")
    try:
        document = read_json(candidate_file)
    except (OSError, ValueError) as exc:
        raise FindingCandidateError(f"cannot read FindingCandidate artifact: {path}") from exc
    validate_finding_candidates(document)
    if document.get("node_id") != node_id:
        raise FindingCandidateError("FindingCandidate Node binding changed")
    intent_id = str(document.get("intent_id") or "")
    if intent_id != parts[3]:
        raise FindingCandidateError("FindingCandidate Attempt binding changed")
    attempt_root = workspace / "nodes" / node_id / "attempts" / intent_id
    if has_symlink_component(workspace, attempt_root):
        raise FindingCandidateError("FindingCandidate Attempt path uses a symbolic link")
    try:
        intent = _read_bound_attempt_object(attempt_root / "intent.json", workspace)
        prepared = _read_bound_attempt_object(attempt_root / "prepared.json", workspace)
        result = _read_bound_attempt_object(
            attempt_root / "outputs" / "calculation_result.json", workspace
        )
    except FindingCandidateError:
        raise
    except (OSError, ValueError) as exc:
        raise FindingCandidateError("FindingCandidate has no valid bound calculation record") from exc
    if not isinstance(intent, dict) or intent.get("schema_version") != "ts-calculation-intent/7":
        raise FindingCandidateError("FindingCandidate has no valid bound calculation intent")
    if not isinstance(prepared, dict) or prepared.get("schema_version") != "ts-compute-prepared/1":
        raise FindingCandidateError("FindingCandidate has no valid prepared calculation binding")
    if (
        prepared.get("intent_id") != intent_id
        or prepared.get("node_id") != node_id
        or prepared.get("intent_ref")
        != f"nodes/{node_id}/attempts/{intent_id}/intent.json"
        or prepared.get("intent_digest") != sha256_json(intent)
        or not isinstance(prepared.get("prepared_task"), dict)
        or not isinstance(prepared.get("execution_policy"), dict)
    ):
        raise FindingCandidateError("FindingCandidate prepared calculation binding changed")
    if not isinstance(result, dict) or result.get("schema_version") != "ts-calculation-result/2":
        raise FindingCandidateError("FindingCandidate has no valid bound calculation result")
    try:
        validate_calculation_result_binding(
            intent,
            result,
            label="FindingCandidate calculation result",
        )
    except CalculationContractError as exc:
        raise FindingCandidateError(str(exc)) from exc
    if (
        result.get("state") != "parsed"
        or result.get("intent_id") != intent_id
        or result.get("node_id") != node_id
        or document.get("capability") != intent.get("capability")
        or document.get("capability_version") != intent.get("capability_version")
    ):
        raise FindingCandidateError("FindingCandidate calculation binding changed")
    result_refs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), list) else []
    if path not in result_refs:
        raise FindingCandidateError("FindingCandidate is not declared by its calculation result")
    result_provenance = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
    if (
        result_provenance.get("parser_name") != document["parser"]["name"]
        or result_provenance.get("parser_contract") != document["parser"]["contract"]
        or result_provenance.get("finding_candidates_ref") != path
        or result_provenance.get("finding_candidates_sha256") != artifact["sha256"]
    ):
        raise FindingCandidateError("FindingCandidate parser binding changed")
    matches = [item for item in document["candidates"] if item.get("candidate_id") == candidate_id]
    if len(matches) != 1:
        raise FindingCandidateError(f"unknown FindingCandidate: {candidate_id}")
    source_records = []
    for source in document["source_artifacts"]:
        if source["path"] not in result_refs:
            raise FindingCandidateError(
                f"FindingCandidate source is outside its calculation result: {source['artifact_id']}"
            )
        try:
            current = resolve_workspace_artifact_ids(root, [source["artifact_id"]])[0]
        except (WorkspaceArtifactError, IndexError) as exc:
            raise FindingCandidateError(
                f"FindingCandidate source artifact changed: {source['artifact_id']}"
            ) from exc
        if current["sha256"] != source["sha256"] or current["path"] != source["path"]:
            raise FindingCandidateError(
                f"FindingCandidate source artifact changed: {source['artifact_id']}"
            )
        source_records.append(current)
    return {
        "document": document,
        "candidate": deepcopy(matches[0]),
        "candidate_artifact": artifact,
        "source_artifacts": source_records,
    }


def _read_bound_attempt_object(path: Path, workspace: Path) -> dict[str, Any]:
    """Read one Attempt document without following links or external paths."""

    if has_symlink_component(workspace, path) or path.is_symlink():
        raise FindingCandidateError(
            "FindingCandidate Attempt document uses a symbolic link"
        )
    if not path.is_file():
        raise FindingCandidateError(
            f"FindingCandidate Attempt document is missing: {path.name}"
        )
    value = read_json(path)
    if not isinstance(value, dict):
        raise FindingCandidateError(
            f"FindingCandidate Attempt document is not an object: {path.name}"
        )
    return value


def _source_binding(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": str(value["artifact_id"]),
        "path": str(value["path"]),
        "sha256": str(value["sha256"]),
    }


def _datatype(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return "number_array"
        if all(isinstance(item, str) for item in value):
            return "string_array"
        return "json"
    if isinstance(value, dict):
        return "object"
    return "json"


def _concept_key(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return normalized or "value"


def _unit_for_key(value: str) -> str | None:
    lowered = value.lower()
    if "cm-1" in lowered:
        return "cm-1"
    if lowered.endswith("_ev") or "_ev_" in lowered:
        return "eV"
    if "hartree" in lowered or "energy" in lowered or "enthalpy" in lowered:
        return "hartree"
    if "angstrom" in lowered or "distance" in lowered:
        return "angstrom"
    return None


def _json_value(value: Any) -> bool:
    try:
        json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError):
        return False
    return True


def _datatype_matches(datatype: str, value: Any) -> bool:
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
        return isinstance(value, list) and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
        )
    if datatype == "object":
        return isinstance(value, dict)
    return _json_value(value)


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


__all__ = [
    "CANDIDATE_FILE_NAME",
    "CANDIDATE_SCHEMA",
    "CANDIDATE_SCHEMA_VERSION",
    "MAX_CANDIDATE_BYTES",
    "FindingCandidateError",
    "build_finding_candidates",
    "load_finding_candidate",
    "validate_finding_candidates",
]
