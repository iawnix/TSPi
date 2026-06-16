"""Contracts and constants for ChemGate workspace validation."""

from __future__ import annotations

from transition_state_workflow.base.findings import WorkspaceValidationFinding as Finding


REFLECTION_TEMPLATE_MARKERS = {"Not run yet.", "Pending."}
PRE_EXECUTION_EVIDENCE_KEYS = {"hypothesis", "decision_card", "reflection", "inputs", "outputs"}
REGISTRY_REQUIRED_SUFFIXES = {".json", ".out", ".log", ".xyz", ".csv", ".txt"}
ENGINE_ROOT_ARTIFACT_NAMES = {
    "charges",
    "coord",
    "energy",
    "g16_driver.out",
    "gradient",
    "hessian",
    "run_metadata.txt",
    "runner.nohup",
    "wbo",
    "xtb.trj",
    "xtbopt.xyz",
    "xtbrestart",
}
ENGINE_ROOT_ARTIFACT_STEM_SUFFIXES = {
    ".g16_driver.out",
    ".run_gaussian_on_compute.sh",
    ".run_metadata.txt",
    ".runner.nohup",
    ".submit_receipt.txt",
}
ENGINE_ROOT_ARTIFACT_SUFFIXES = {".chk", ".fchk", ".rwf", ".mwfn", ".trj", ".gbw", ".hess"}
GAUSSIAN_INPUT_SUFFIXES = {".gjf", ".com"}


__all__ = [
    "Finding",
    "REFLECTION_TEMPLATE_MARKERS",
    "PRE_EXECUTION_EVIDENCE_KEYS",
    "REGISTRY_REQUIRED_SUFFIXES",
    "ENGINE_ROOT_ARTIFACT_NAMES",
    "ENGINE_ROOT_ARTIFACT_STEM_SUFFIXES",
    "ENGINE_ROOT_ARTIFACT_SUFFIXES",
    "GAUSSIAN_INPUT_SUFFIXES",
]
