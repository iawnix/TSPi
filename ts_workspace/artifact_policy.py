"""Artifact ownership policy for evidence records."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .ontology import node_scope_of, node_type_of


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


def role_matches_node(role: Any, node: Any) -> bool:
    """Whether an evidence role is compatible with a node type and scope."""

    if not isinstance(node, dict):
        return True
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
