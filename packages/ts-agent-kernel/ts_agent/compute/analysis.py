"""Registry for deterministic scientific analysis capabilities.

Analysis capabilities operate on existing Node/artifact inputs.  They are
kept separate from the external-program calculation catalog so adding one does
not imply a scheduler task or a scientific successor workflow.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from jsonschema import Draft202012Validator

from .contracts import ComputeContractError
from ts_agent.analysis.catalog import DESCRIPTORS


ATOM_REFERENCE = {
    "type": "object",
    "required": ["species", "atom"],
    "properties": {
        "species": {"type": "integer", "minimum": 0, "maximum": 63},
        "atom": {"type": "integer", "minimum": 0, "maximum": 4095},
    },
    "additionalProperties": False,
}
SPECIES_ARTIFACTS = {
    "type": "array",
    "items": {"type": "string", "pattern": "^art_[0-9a-f]{24}$"},
    "minItems": 1,
    "maxItems": 64,
}

ANALYSIS_DESCRIPTORS: Final[tuple[dict[str, Any], ...]] = (
    {
        "capability": "reaction.mapping.validate",
        "version": "1",
        "capability_kind": "analysis",
        "summary": "Check an explicit element-preserving atom bijection across ordered XYZ species.",
        "input_roles": ["reactants", "products"],
        "output_roles": ["mapping_validation", "analysis_artifact", "observation_candidates"],
        "effects": ["local_prepare", "local_analysis"],
        "input_schema": {
            "type": "object",
            "required": ["reactants", "products"],
            "properties": {"reactants": SPECIES_ARTIFACTS, "products": SPECIES_ARTIFACTS},
            "additionalProperties": False,
        },
        "parameter_schema": {
            "type": "object",
            "required": ["mapping"],
            "properties": {
                "mapping": {
                    "type": "array",
                    "maxItems": 4096,
                    "items": {
                        "type": "object",
                        "required": ["reactant", "product"],
                        "properties": {"reactant": ATOM_REFERENCE, "product": ATOM_REFERENCE},
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        "limits": {"max_species_per_side": 64, "max_atoms_per_species": 4096, "max_atoms_per_side": 4096, "max_mapping_pairs": 4096},
        "parsers": ["ts.reaction.mapping/1"],
        "scientific_scope": "Validate an explicit atom mapping; does not generate one.",
        "limitations": [
            "Ambiguous symmetry and proton-transfer choices remain unresolved.",
            "Input XYZ atom identity and element labels must already be reliable.",
            "Element agreement does not validate isotope, charge, spin, connectivity, or chemical plausibility.",
        ],
    },
) + DESCRIPTORS

ANALYSIS_CAPABILITIES_BY_ID: Final[dict[str, dict[str, Any]]] = {
    item["capability"]: item for item in ANALYSIS_DESCRIPTORS
}


def analysis_capabilities() -> dict[str, Any]:
    """Return the analysis catalog without asserting scientific readiness."""

    return {
        "schema_version": "ts-analysis-capability-catalog/1",
        "capability_kind": "analysis",
        "capabilities": [
            {key: deepcopy(item[key]) for key in (
                "capability", "version", "capability_kind", "summary", "input_roles", "output_roles"
            )}
            for item in ANALYSIS_DESCRIPTORS
        ],
        "detail_query": "ts_state mode=capabilities capabilityKind=analysis query=<capability>@<version>",
    }


def resolve_analysis_capability(capability: str, version: str = "1") -> dict[str, Any]:
    descriptor = ANALYSIS_CAPABILITIES_BY_ID.get(capability)
    if descriptor is None or descriptor["version"] != version:
        return {
            "schema_version": "ts-capability-gap/1",
            "ok": False,
            "status": "rejected",
            "reason": "capability_unavailable",
            "requested": f"{capability}@{version}",
            "missing_capability": capability,
            "requested_version": version,
            "retryable": False,
        }
    return {"schema_version": "ts-analysis-capability-resolution/1", "ok": True, **deepcopy(descriptor)}


def run_analysis(root: str, request: dict[str, Any]) -> dict[str, Any]:
    """Dispatch an exact registered capability with validated, bounded inputs."""

    required = {"schema_version", "node_id", "capability", "capability_version", "input_artifacts", "parameters"}
    if not isinstance(request, dict) or set(request) != required:
        raise ComputeContractError("analysis request fields must be " + ", ".join(sorted(required)))
    if request["schema_version"] != "ts-analysis-request/1":
        raise ComputeContractError("analysis schema_version must be ts-analysis-request/1")
    capability, version = request["capability"], request["capability_version"]
    if not isinstance(capability, str) or not isinstance(version, str):
        raise ComputeContractError("analysis capability and capability_version must be strings")
    descriptor = resolve_analysis_capability(capability, version)
    if not descriptor["ok"]:
        return descriptor
    for field, schema in (("input_artifacts", "input_schema"), ("parameters", "parameter_schema")):
        error = next(Draft202012Validator(descriptor[schema]).iter_errors(request[field]), None)
        if error is not None:
            location = ".".join([field, *(str(part) for part in error.absolute_path)])
            raise ComputeContractError(f"analysis {location}: {error.message}")
    if capability != "reaction.mapping.validate":
        from ts_agent.analysis.engine import run_scientific_analysis
        return run_scientific_analysis(root, request)
    # Imports stay local: catalog discovery does not load scientific libraries.
    from .artifacts import create_reaction_mapping_validation_artifact

    result = create_reaction_mapping_validation_artifact(root, {
        "schema_version": "ts-reaction-mapping-validate-request/1",
        "node_id": request["node_id"],
        "reactants": [{"artifact_id": item} for item in request["input_artifacts"]["reactants"]],
        "products": [{"artifact_id": item} for item in request["input_artifacts"]["products"]],
        "mapping": request["parameters"]["mapping"],
    })
    return {
        **result,
        "schema_version": "ts-analysis-result/1",
        "analysis_schema_version": result["schema_version"],
        "operation": "run",
        "summary": f"{capability}@{version}: {result['verdict']}; {result['mapping_count']} mapped atom pairs.",
    }
