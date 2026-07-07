"""Artifact ownership policy for evidence records."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


MECHANISM_REFLECTION_PHASES = {
    "endpoint",
    "preflight",
    "candidate_generation",
    "tsfreq_validation",
    "connectivity_validation",
    "accepted_audit",
    "pathway_audit",
}

ROLE_PHASE_OWNER = {
    "endpoint_provenance": "endpoint",
    "charge_multiplicity": "endpoint",
    "atom_mapping": "endpoint",
    "reaction_center_delta": "endpoint",
    "initial_mechanism_hypothesis": "endpoint",
    "candidate_geometry": "candidate_generation",
    "candidate_generation_log": "candidate_generation",
    "tsfreq_gate": "tsfreq_validation",
    "mode_assignment": "tsfreq_validation",
    "connectivity_gate": "connectivity_validation",
    "irc_endpoint_assignment": "connectivity_validation",
    "stereochemical_connectivity_gate": "connectivity_validation",
    "endpoint_identity_gate": MECHANISM_REFLECTION_PHASES,
    "intermediate_identity_gate": MECHANISM_REFLECTION_PHASES,
    "electronic_structure_gate": MECHANISM_REFLECTION_PHASES,
    "state_character_gate": MECHANISM_REFLECTION_PHASES,
    "shared_basin_consistency_gate": MECHANISM_REFLECTION_PHASES,
    "accepted_audit": "accepted_audit",
    "pathway_audit": "pathway_audit",
    "pathway_audit_summary": "pathway_audit",
}

INITIAL_PHASES = {"endpoint", "preflight"}


def expected_phase_for_role(role: Any) -> Any:
    """Return the node phase that owns a structured evidence role."""

    if not isinstance(role, str):
        return None
    return ROLE_PHASE_OWNER.get(role)


def role_matches_phase(role: Any, phase: Any) -> bool:
    """Whether an evidence role is compatible with a node phase."""

    expected = expected_phase_for_role(role)
    if expected is None:
        return True
    if isinstance(expected, (set, frozenset, list, tuple)):
        return phase in expected
    if expected == "endpoint":
        return phase in INITIAL_PHASES
    return phase == expected


def node_owner_from_artifact_path(path: Any) -> str | None:
    """Extract ``nodes/<node_id>`` ownership from a relative or absolute path."""

    if not isinstance(path, str) or not path.strip():
        return None
    parts = PurePosixPath(path.strip()).parts
    for index, part in enumerate(parts[:-1]):
        if part == "nodes":
            return parts[index + 1]
    return None


def consumed_paths_from_manifest(manifest: Any) -> set[str]:
    """Return consumed artifact paths declared by a node artifact manifest."""

    if not isinstance(manifest, dict):
        return set()
    paths: set[str] = set()
    for item in manifest.get("consumed_artifacts", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.add(item["path"])
    return paths
