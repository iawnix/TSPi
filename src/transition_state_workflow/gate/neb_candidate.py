"""NEB candidate validation policy gates.

This module owns backend-agnostic policy for turning a candidate path plus
endpoint references into follow-up validation requirements. It does not run
ASE, Gaussian, or xTB, and it does not mutate TS-search workspace state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.chem.geometry import (
    angle_label,
    atom_indices_from_bonds_angles,
    bond_label,
    changed_bonds,
    infer_angles,
    read_xyz_with_comment,
)
from transition_state_workflow.chem.mechanism import classify_validation_system


def displacement_ladder(system_class: str, imaginary_frequency: float | None) -> list[float]:
    """Return max-atom displacement values for imaginary-mode endpoint follow-up."""

    if system_class == "h_transfer":
        ladder = [0.08, 0.15, 0.25]
    elif system_class == "metal":
        ladder = [0.10, 0.20, 0.30, 0.45]
    elif system_class == "flexible":
        ladder = [0.15, 0.25, 0.35, 0.50]
    else:
        ladder = [0.15, 0.25, 0.35]
    if imaginary_frequency is not None and abs(imaginary_frequency) < 80.0:
        return sorted(set([0.08, *ladder]))
    return ladder


def threshold_policy(system_class: str) -> dict[str, dict[str, float]]:
    """Return structural-connectivity pass/borderline thresholds."""

    common = {
        "angle_deg": {"pass": 8.0, "borderline": 15.0},
        "reaction_center_rmsd_a": {"pass": 0.35, "borderline": 0.50},
    }
    if system_class == "h_transfer":
        return {
            **common,
            "heavy_atom_rmsd_a": {"pass": 0.35, "borderline": 0.75},
            "key_bond_a": {"pass": 0.12, "borderline": 0.20},
            "h_transfer_bond_a": {"pass": 0.12, "borderline": 0.20},
        }
    if system_class == "metal":
        return {
            **common,
            "heavy_atom_rmsd_a": {"pass": 0.50, "borderline": 1.00},
            "key_bond_a": {"pass": 0.25, "borderline": 0.35},
            "metal_ligand_bond_a": {"pass": 0.25, "borderline": 0.35},
        }
    if system_class == "flexible":
        return {
            **common,
            "heavy_atom_rmsd_a": {"pass": 0.75, "borderline": 1.50},
            "key_bond_a": {"pass": 0.15, "borderline": 0.25},
        }
    return {
        **common,
        "heavy_atom_rmsd_a": {"pass": 0.35, "borderline": 0.75},
        "key_bond_a": {"pass": 0.15, "borderline": 0.25},
    }


def irc_policy(
    *,
    system_class: str,
    bonds: list[tuple[int, int]],
    imaginary_frequency: float | None,
    publication_grade: bool,
    force_irc: bool,
    flags: list[str],
) -> dict[str, Any]:
    """Return whether IRC is optional, recommended, or required."""

    reasons: list[str] = []
    level = "optional_after_strong_endpoint_match"
    if publication_grade:
        level = "required"
        reasons.append("publication-grade or final claim requested")
    if force_irc:
        level = "required"
        reasons.append("explicit force_irc requested")
    if not bonds:
        level = "required"
        reasons.append("reaction-center bonds could not be inferred")
    if imaginary_frequency is not None and abs(imaginary_frequency) < 80.0:
        level = "required"
        reasons.append("small imaginary frequency suggests a shallow or conformational mode")
    if system_class in {"metal", "flexible"} and level != "required":
        level = "recommended"
        reasons.append(f"{system_class} system has higher endpoint-optimization ambiguity")
    for flag in flags:
        level = "required"
        reasons.append(flag.replace("_", " "))
    if not reasons:
        reasons.append("endpoint validation may be sufficient if both endpoints pass strict gates")
    return {"policy": level, "reasons": reasons}


def build_validation_policy(
    reactant_path: Path,
    product_path: Path,
    *,
    user_bonds: list[tuple[int, int]] | None = None,
    user_angles: list[tuple[int, int, int]] | None = None,
    system_class_override: str = "auto",
    imaginary_frequency: float | None = None,
    publication_grade: bool = False,
    force_irc: bool = False,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Build a backend-agnostic TS connectivity validation policy payload."""

    reactant, _ = read_xyz_with_comment(reactant_path)
    product, _ = read_xyz_with_comment(product_path)
    if len(reactant) != len(product):
        raise ValueError("reactant/product atom count mismatch")
    if [atom.element for atom in reactant] != [atom.element for atom in product]:
        raise ValueError("reactant/product atom order mismatch")
    changed = changed_bonds(reactant, product, user_bonds=user_bonds)
    bonds = sorted(set(changed["user"] + changed["formed"] + changed["broken"]))
    angles = infer_angles(reactant, product, bonds, user_angles=user_angles)
    system_class = classify_validation_system(
        reactant,
        bonds,
        override=system_class_override,
    )
    flags = risk_flags or []
    return {
        "schema": "ts-validation-policy-v2",
        "reactant": str(reactant_path),
        "product": str(product_path),
        "system_class": system_class,
        "reaction_center": {
            "source": "user" if user_bonds else "inferred_from_reactant_product_connectivity",
            "formed_bonds": [bond_label(bond) for bond in changed["formed"]],
            "broken_bonds": [bond_label(bond) for bond in changed["broken"]],
            "tracked_bonds": [bond_label(bond) for bond in bonds],
            "tracked_angles": [angle_label(angle) for angle in angles],
            "tracked_atom_indices": atom_indices_from_bonds_angles(bonds, angles),
        },
        "imaginary_mode_follow": {
            "displacement_ladder_max_atom_a": displacement_ladder(system_class, imaginary_frequency),
            "endpoint_opt_route_policy": "ordinary Opt(MaxCycle=100); avoid CalcFC unless explicitly needed",
            "retry_rule": "try the next displacement only when endpoints collapse to the same basin or remain TS-like",
        },
        "connectivity_metrics": {
            "assignment": "accept either plus=reactant/minus=product or plus=product/minus=reactant",
            "use_full_molecule_rmsd_as_auxiliary": system_class not in {"flexible", "metal"},
            "primary_gates": [
                "reaction_center_rmsd_a",
                "tracked_bond_delta_a",
                "tracked_angle_delta_deg",
            ],
            "thresholds": threshold_policy(system_class),
        },
        "irc_decision": irc_policy(
            system_class=system_class,
            bonds=bonds,
            imaginary_frequency=imaginary_frequency,
            publication_grade=publication_grade,
            force_irc=force_irc,
            flags=flags,
        ),
        "acceptance_policy": {
            "tsfreq_validated": "normal termination + stationary point + exactly one imaginary frequency",
            "mode_endpoint_connected": "both +/- optimized endpoints match different R/P references under all primary gates",
            "irc_connected": "forward/reverse IRC endpoints match different R/P references under all primary gates",
            "accepted_ts_default": "tsfreq_validated + irc_connected",
            "accepted_ts_fallback": "tsfreq_validated + mode_endpoint_connected, explicitly marked not IRC-confirmed",
        },
    }


__all__ = [
    "build_validation_policy",
    "displacement_ladder",
    "irc_policy",
    "threshold_policy",
]
