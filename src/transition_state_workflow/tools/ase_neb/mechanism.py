"""ASE NEB adapters over shared mechanism-preflight helpers."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.chem import mechanism as chem_mechanism
from transition_state_workflow.tools.ase_neb.coerce import as_mapping
from transition_state_workflow.tools.ase_neb.geometry import xyz_atoms_from_ase

ENDPOINT_READY_STATES = chem_mechanism.ENDPOINT_READY_STATES
ENDPOINT_STATE_CHOICES = chem_mechanism.ENDPOINT_STATE_CHOICES
classify_validation_system = chem_mechanism.classify_validation_system


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

    return chem_mechanism.infer_mechanism_preflight_from_geometry(
        reactant=xyz_atoms_from_ase(reactant),
        product=xyz_atoms_from_ase(product),
        charge=charge,
        multiplicity=multiplicity,
        xtb_uhf=calc_uhf,
        calculator_type=calc_cfg.get("type"),
        calculator_charge=calc_charge,
        validation_charge=gaussian_charge,
        validation_multiplicity=gaussian_multiplicity,
    )


def endpoint_validation_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return normalized endpoint-readiness metadata for candidate gating."""

    return chem_mechanism.endpoint_readiness_summary(cfg.get("endpoint_validation", {}))


__all__ = [
    "ENDPOINT_READY_STATES",
    "ENDPOINT_STATE_CHOICES",
    "classify_validation_system",
    "infer_mechanism_preflight",
    "endpoint_validation_summary",
]
