"""Artifact ownership policy for evidence records."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .ontology import node_scope_of, node_type_of


MECHANISM_REFLECTION_PHASES = {
    "endpoint",
    "hypothesis_generation",
    "preflight",
    "rp_conformer_generation",
    "candidate_generation",
    "tsfreq_validation",
    "connectivity_validation",
    "accepted_audit",
    "pathway_audit",
}

ROLE_PHASE_OWNER = {
    "endpoint_provenance": {"endpoint", "preflight"},
    "charge_multiplicity": {"endpoint", "preflight"},
    "atom_mapping": {"endpoint", "preflight"},
    "reaction_center_delta": {"endpoint", "preflight"},
    "initial_mechanism_hypothesis": {"endpoint", "hypothesis_generation", "preflight"},
    "endpoint_conformer_ensemble": {"candidate_generation", "rp_conformer_generation"},
    "selected_endpoint_conformer": {"candidate_generation", "rp_conformer_generation"},
    "endpoint_minimum_gate": {"endpoint", "candidate_generation", "preflight", "rp_conformer_generation"},
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

ROLE_NODE_OWNER = {
    "endpoint_provenance": {"intake": None},
    "charge_multiplicity": {"intake": None},
    "atom_mapping": {"intake": None},
    "reaction_center_delta": {"intake": None},
    "initial_mechanism_hypothesis": {"mechanism": {"propose"}},
    "endpoint_conformer_ensemble": {"candidate_search": {"endpoint_conformer"}},
    "selected_endpoint_conformer": {"candidate_search": {"endpoint_conformer"}},
    "endpoint_minimum_gate": {
        "candidate_search": {"endpoint_conformer"},
        "validation": {"geometry_identity"},
    },
    "candidate_geometry": {"candidate_search": None},
    "candidate_generation_log": {"candidate_search": None},
    "tsfreq_gate": {"validation": {"tsfreq"}},
    "mode_assignment": {"validation": {"tsfreq"}},
    "connectivity_gate": {"validation": {"connectivity"}},
    "irc_endpoint_assignment": {"validation": {"connectivity"}},
    "stereochemical_connectivity_gate": {"validation": {"connectivity"}},
    "endpoint_identity_gate": {"validation": {"geometry_identity", "electronic_structure"}},
    "intermediate_identity_gate": {"validation": {"geometry_identity", "electronic_structure"}},
    "electronic_structure_gate": {"validation": {"electronic_structure"}},
    "state_character_gate": {"validation": {"state_character"}},
    "shared_basin_consistency_gate": {"validation": {"connectivity", "geometry_identity"}},
    "accepted_audit": {"audit": {"transition_state", "elementary_step"}},
    "pathway_audit": {"audit": {"pathway"}},
    "pathway_audit_summary": {"audit": {"pathway"}},
}


def expected_phase_for_role(role: Any) -> Any:
    """Return the node phase or compatible phases for an evidence role."""

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
    return phase == expected


def role_matches_node(role: Any, node: Any) -> bool:
    """Whether an evidence role is compatible with a v2 or legacy node."""

    if not isinstance(node, dict):
        return True
    if node.get("schema_version") != "ts-node/2":
        return role_matches_phase(role, node.get("phase"))
    if not isinstance(role, str):
        return True
    expected = ROLE_NODE_OWNER.get(role)
    if expected is None:
        return True
    node_type = node_type_of(node)
    if node_type not in expected:
        return False
    scopes = expected[node_type]
    return scopes is None or node_scope_of(node) in scopes


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
