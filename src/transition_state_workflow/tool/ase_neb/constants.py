"""Constants shared across the NEB toolkit."""

from __future__ import annotations

from transition_state_workflow.chem.geometry import COVALENT_RADII

CONFIG_VERSION = 1
SUPPORTED_CALCULATORS = {"xtb", "gaussian", "gaussian_external"}
SUPPORTED_INTERPOLATION = {"linear", "idpp"}
OPTIMIZER_NAMES = {"FIRE", "BFGS", "LBFGS", "MDMin"}
TREE_SCHEMA_VERSION = 2

HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANG = 0.529177210903
HARTREE_PER_BOHR_TO_EV_PER_ANG = HARTREE_TO_EV / BOHR_TO_ANG

VALID_NODE_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "ambiguous",
    "accepted",
    "closed",
}
ACTIVE_NODE_STATUSES = {"pending", "running", "ambiguous"}

METALS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe",
    "Co", "Ni", "Cu", "Zn", "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru",
    "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
}

__all__ = [
    "COVALENT_RADII",
    "CONFIG_VERSION",
    "SUPPORTED_CALCULATORS",
    "SUPPORTED_INTERPOLATION",
    "OPTIMIZER_NAMES",
    "TREE_SCHEMA_VERSION",
    "HARTREE_TO_EV",
    "BOHR_TO_ANG",
    "HARTREE_PER_BOHR_TO_EV_PER_ANG",
    "VALID_NODE_STATUSES",
    "ACTIVE_NODE_STATUSES",
    "METALS",
]
