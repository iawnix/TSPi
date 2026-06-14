"""Constants shared across the NEB toolkit."""

from __future__ import annotations

from transition_state_workflow.base.ase_neb import (
    ACTIVE_NODE_STATUSES,
    VALID_NODE_STATUSES,
)
from transition_state_workflow.chem.geometry import COVALENT_RADII
from transition_state_workflow.chem.mechanism import METALS

CONFIG_VERSION = 1
SUPPORTED_CALCULATORS = {"xtb", "gaussian", "gaussian_external"}
SUPPORTED_INTERPOLATION = {"linear", "idpp"}
OPTIMIZER_NAMES = {"FIRE", "BFGS", "LBFGS", "MDMin"}
TREE_SCHEMA_VERSION = 2

HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANG = 0.529177210903
HARTREE_PER_BOHR_TO_EV_PER_ANG = HARTREE_TO_EV / BOHR_TO_ANG

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
