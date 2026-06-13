"""Mechanism preflight, system classification, and endpoint-readiness gating.

Pure functions over config and geometry: classify a reaction system, infer a
coarse task-start mechanism hypothesis from charge/spin/connectivity, and
summarize whether the declared reactant/product endpoints are ready to gate a
candidate. No workspace or ASE state lives here.
"""

from __future__ import annotations

from typing import Any

from transition_state_workflow.tools.ase_neb.coerce import as_mapping
from transition_state_workflow.tools.ase_neb.constants import METALS
from transition_state_workflow.tool.ase_neb.geometry import (
    Atom,
    angle_label,
    bond_label,
    changed_bonds,
    fragment_labels,
    infer_angles,
    xyz_atoms_from_ase,
)

ENDPOINT_READY_STATES = ("validated_minimum", "lower_level_minimum", "constrained_reference")
ENDPOINT_STATE_CHOICES = ("reference_hypothesis", *ENDPOINT_READY_STATES)


def classify_validation_system(
    atoms: list[Atom],
    bonds: list[tuple[int, int]],
    *,
    override: str = "auto",
) -> str:
    if override != "auto":
        return override
    changed_atoms = {index for bond in bonds for index in bond}
    changed_symbols = {atoms[index - 1].element for index in changed_atoms if 0 < index <= len(atoms)}
    if changed_symbols & METALS:
        return "metal"
    if "H" in changed_symbols:
        return "h_transfer"
    if len(atoms) <= 40 and len(bonds) <= 4:
        return "small_rigid"
    return "flexible"


def infer_mechanism_preflight(
    cfg: dict[str, Any],
    reactant: Any,
    product: Any,
) -> dict[str, Any]:
    calc_cfg = as_mapping(cfg.get("calculator"), "calculator")
    gaussian_cfg = as_mapping(cfg.get("refinement"), "refinement").get("gaussian", {})
    gaussian_cfg = as_mapping(gaussian_cfg, "refinement.gaussian")
    calc_charge = calc_cfg.get("charge")
    calc_uhf = calc_cfg.get("uhf")
    gaussian_charge = gaussian_cfg.get("charge")
    gaussian_multiplicity = gaussian_cfg.get("multiplicity")
    charge = gaussian_charge if gaussian_charge is not None else calc_charge
    multiplicity = gaussian_multiplicity
    if multiplicity is None and calc_uhf is not None:
        multiplicity = int(calc_uhf) + 1

    reactant_xyz = xyz_atoms_from_ase(reactant)
    product_xyz = xyz_atoms_from_ase(product)
    changed = changed_bonds(reactant_xyz, product_xyz)
    bonds = sorted(set(changed["user"] + changed["formed"] + changed["broken"]))
    angles = infer_angles(reactant_xyz, product_xyz, bonds)
    changed_atoms = {index for bond in bonds for index in bond}
    changed_symbols = sorted(
        {reactant_xyz[index - 1].element for index in changed_atoms if 0 < index <= len(reactant_xyz)}
    )
    system_class = classify_validation_system(reactant_xyz, bonds)

    open_shell = False
    if multiplicity is not None:
        open_shell = int(multiplicity) > 1
    elif calc_uhf is not None:
        open_shell = int(calc_uhf) > 0

    if system_class == "h_transfer" and open_shell:
        reaction_class = "possible_pcet_or_radical_h_transfer"
    elif system_class == "h_transfer":
        reaction_class = "proton_or_hydrogen_transfer"
    elif system_class == "metal":
        reaction_class = "metal_ligand_rearrangement"
    elif changed["formed"] and changed["broken"]:
        reaction_class = "bond_rearrangement"
    elif changed["formed"]:
        reaction_class = "association_or_bond_formation"
    elif changed["broken"]:
        reaction_class = "dissociation_or_bond_cleavage"
    elif bonds:
        reaction_class = "large_geometry_change_without_clear_bond_order_change"
    else:
        reaction_class = "unknown_or_conformational"

    risk_flags: list[str] = []
    if charge not in (None, 0):
        risk_flags.append("charged_system")
    if open_shell:
        risk_flags.append("open_shell_or_radical_state")
    if system_class == "h_transfer" and open_shell:
        risk_flags.append("monitor_coupled_proton_electron_transfer")
    if calc_cfg.get("type") == "xtb" and open_shell:
        risk_flags.append("xtb_open_shell_surface_is_screening_only")
    if calc_charge is not None and gaussian_charge is not None and int(calc_charge) != int(gaussian_charge):
        risk_flags.append("calculator_gaussian_charge_mismatch")
    if calc_uhf is not None and gaussian_multiplicity is not None and int(calc_uhf) + 1 != int(gaussian_multiplicity):
        risk_flags.append("calculator_gaussian_spin_mismatch")
    if not bonds:
        risk_flags.append("reaction_center_not_inferred")
    mechanism_confidence = "low" if risk_flags else "medium"

    validation_observables = [
        "imaginary_mode_matches_reaction_center",
        "endpoint_connectivity_to_prepared_reactant_product",
        "tracked_bond_lengths",
        "tracked_angles",
    ]
    if open_shell:
        validation_observables.extend(["spin_density_by_fragment", "spin_contamination_s2"])
    if charge not in (None, 0):
        validation_observables.append("fragment_charges")

    return {
        "source": "inferred_from_total_charge_spin_and_reactant_product_connectivity",
        "total_charge": charge,
        "multiplicity": multiplicity,
        "xtb_uhf": calc_uhf,
        "electronic_state": "open_shell" if open_shell else "closed_shell_or_spin_unset",
        "mechanism_hypothesis": reaction_class,
        "mechanism_confidence": mechanism_confidence,
        "reaction_class": reaction_class,
        "system_class": system_class,
        "reactant_fragments": fragment_labels(reactant_xyz),
        "product_fragments": fragment_labels(product_xyz),
        "formed_bonds": [bond_label(bond) for bond in changed["formed"]],
        "broken_bonds": [bond_label(bond) for bond in changed["broken"]],
        "tracked_bonds": [bond_label(bond) for bond in bonds],
        "tracked_angles": [angle_label(angle) for angle in angles],
        "changed_atom_symbols": changed_symbols,
        "likely_charge_spin_carriers": "fragment-level population analysis required; do not infer from total state alone",
        "mechanism_note": "Coarse task-start hypothesis only; validate with reaction-center geometry, endpoint connectivity, and population/spin analysis when relevant.",
        "risk_flags": risk_flags,
        "validation_observables": validation_observables,
    }


def endpoint_validation_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return normalized endpoint-readiness metadata for candidate gating."""

    endpoint_validation = cfg.get("endpoint_validation", {})
    reactant_state = str(endpoint_validation.get("reactant_state") or "reference_hypothesis")
    product_state = str(endpoint_validation.get("product_state") or "reference_hypothesis")
    ready_states = set(ENDPOINT_READY_STATES)
    return {
        "reactant_state": reactant_state,
        "product_state": product_state,
        "level": str(endpoint_validation.get("level") or ""),
        "evidence": str(endpoint_validation.get("evidence") or ""),
        "allowed_ready_states": sorted(ready_states),
        "endpoint_minima_ready": reactant_state in ready_states and product_state in ready_states,
    }


__all__ = [
    "ENDPOINT_READY_STATES",
    "ENDPOINT_STATE_CHOICES",
    "classify_validation_system",
    "infer_mechanism_preflight",
    "endpoint_validation_summary",
]
