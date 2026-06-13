"""Reusable mechanism-preflight helpers for TS-search tools."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.chem.geometry import (
    Atom,
    angle_label,
    bond_label,
    changed_bonds,
    fragment_labels,
    infer_angles,
)


METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe",
    "Co", "Ni", "Cu", "Zn", "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru",
    "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
}

ENDPOINT_READY_STATES = ("validated_minimum", "lower_level_minimum", "constrained_reference")
ENDPOINT_STATE_CHOICES = ("reference_hypothesis", *ENDPOINT_READY_STATES)


def classify_validation_system(
    atoms: list[Atom],
    bonds: list[tuple[int, int]],
    *,
    override: str = "auto",
) -> str:
    """Classify the endpoint-pair validation problem from reaction-center atoms."""

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


def open_shell_from_state(*, multiplicity: Any = None, uhf: Any = None) -> bool:
    """Return whether total spin settings indicate an open-shell surface."""

    if multiplicity is not None:
        return int(multiplicity) > 1
    if uhf is not None:
        return int(uhf) > 0
    return False


def reaction_class_from_connectivity(
    *,
    system_class: str,
    changed: dict[str, list[tuple[int, int]]],
    bonds: list[tuple[int, int]],
    open_shell: bool,
) -> str:
    """Infer a coarse task-start reaction class from connectivity changes."""

    if system_class == "h_transfer" and open_shell:
        return "possible_pcet_or_radical_h_transfer"
    if system_class == "h_transfer":
        return "proton_or_hydrogen_transfer"
    if system_class == "metal":
        return "metal_ligand_rearrangement"
    if changed["formed"] and changed["broken"]:
        return "bond_rearrangement"
    if changed["formed"]:
        return "association_or_bond_formation"
    if changed["broken"]:
        return "dissociation_or_bond_cleavage"
    if bonds:
        return "large_geometry_change_without_clear_bond_order_change"
    return "unknown_or_conformational"


def mechanism_risk_flags(
    *,
    charge: Any = None,
    open_shell: bool,
    system_class: str,
    calculator_type: str | None = None,
    calculator_charge: Any = None,
    calculator_uhf: Any = None,
    validation_charge: Any = None,
    validation_multiplicity: Any = None,
    bonds: list[tuple[int, int]],
) -> list[str]:
    """Return coarse preflight risk flags from electronic state and connectivity."""

    risk_flags: list[str] = []
    if charge not in (None, 0):
        risk_flags.append("charged_system")
    if open_shell:
        risk_flags.append("open_shell_or_radical_state")
    if system_class == "h_transfer" and open_shell:
        risk_flags.append("monitor_coupled_proton_electron_transfer")
    if calculator_type == "xtb" and open_shell:
        risk_flags.append("xtb_open_shell_surface_is_screening_only")
    if calculator_charge is not None and validation_charge is not None and int(calculator_charge) != int(validation_charge):
        risk_flags.append("calculator_gaussian_charge_mismatch")
    if (
        calculator_uhf is not None
        and validation_multiplicity is not None
        and int(calculator_uhf) + 1 != int(validation_multiplicity)
    ):
        risk_flags.append("calculator_gaussian_spin_mismatch")
    if not bonds:
        risk_flags.append("reaction_center_not_inferred")
    return risk_flags


def validation_observables_for_state(*, charge: Any = None, open_shell: bool) -> list[str]:
    """Return mechanism observables expected for follow-up validation."""

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
    return validation_observables


def infer_mechanism_preflight_from_geometry(
    *,
    reactant: list[Atom],
    product: list[Atom],
    charge: Any = None,
    multiplicity: Any = None,
    xtb_uhf: Any = None,
    calculator_type: str | None = None,
    calculator_charge: Any = None,
    validation_charge: Any = None,
    validation_multiplicity: Any = None,
) -> dict[str, Any]:
    """Infer a coarse mechanism preflight from endpoints and spin/charge settings."""

    changed = changed_bonds(reactant, product)
    bonds = sorted(set(changed["user"] + changed["formed"] + changed["broken"]))
    angles = infer_angles(reactant, product, bonds)
    changed_atoms = {index for bond in bonds for index in bond}
    changed_symbols = sorted({reactant[index - 1].element for index in changed_atoms if 0 < index <= len(reactant)})
    system_class = classify_validation_system(reactant, bonds)
    open_shell = open_shell_from_state(multiplicity=multiplicity, uhf=xtb_uhf)
    reaction_class = reaction_class_from_connectivity(
        system_class=system_class,
        changed=changed,
        bonds=bonds,
        open_shell=open_shell,
    )
    risk_flags = mechanism_risk_flags(
        charge=charge,
        open_shell=open_shell,
        system_class=system_class,
        calculator_type=calculator_type,
        calculator_charge=calculator_charge,
        calculator_uhf=xtb_uhf,
        validation_charge=validation_charge,
        validation_multiplicity=validation_multiplicity,
        bonds=bonds,
    )

    return {
        "source": "inferred_from_total_charge_spin_and_reactant_product_connectivity",
        "total_charge": charge,
        "multiplicity": multiplicity,
        "xtb_uhf": xtb_uhf,
        "electronic_state": "open_shell" if open_shell else "closed_shell_or_spin_unset",
        "mechanism_hypothesis": reaction_class,
        "mechanism_confidence": "low" if risk_flags else "medium",
        "reaction_class": reaction_class,
        "system_class": system_class,
        "reactant_fragments": fragment_labels(reactant),
        "product_fragments": fragment_labels(product),
        "formed_bonds": [bond_label(bond) for bond in changed["formed"]],
        "broken_bonds": [bond_label(bond) for bond in changed["broken"]],
        "tracked_bonds": [bond_label(bond) for bond in bonds],
        "tracked_angles": [angle_label(angle) for angle in angles],
        "changed_atom_symbols": changed_symbols,
        "likely_charge_spin_carriers": "fragment-level population analysis required; do not infer from total state alone",
        "mechanism_note": "Coarse task-start hypothesis only; validate with reaction-center geometry, endpoint connectivity, and population/spin analysis when relevant.",
        "risk_flags": risk_flags,
        "validation_observables": validation_observables_for_state(charge=charge, open_shell=open_shell),
    }


def endpoint_readiness_summary(endpoint_validation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return normalized endpoint-readiness metadata for candidate gating."""

    endpoint_validation = endpoint_validation or {}
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
    "METALS",
    "ENDPOINT_READY_STATES",
    "ENDPOINT_STATE_CHOICES",
    "classify_validation_system",
    "open_shell_from_state",
    "reaction_class_from_connectivity",
    "mechanism_risk_flags",
    "validation_observables_for_state",
    "infer_mechanism_preflight_from_geometry",
    "endpoint_readiness_summary",
]
