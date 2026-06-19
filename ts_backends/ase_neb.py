"""ASE NEB candidate path command preparation."""

from __future__ import annotations

from .base import BackendTask, PreparedTask


def prepare_ase_neb(task: BackendTask) -> PreparedTask:
    reactant = task.inputs["reactant"]
    product = task.inputs["product"]
    images = task.settings.get("images", "7")
    return PreparedTask(
        backend="ase_neb",
        node_id=task.node_id,
        command=["python", "-m", "ase", "neb", "--images", images, reactant, product],
        input_paths=[reactant, product],
        expected_artifacts=["neb.traj", "neb_summary.json"],
    )
