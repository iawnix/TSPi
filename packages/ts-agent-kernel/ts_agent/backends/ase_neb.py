"""ASE NEB candidate path command preparation."""

from __future__ import annotations

from ts_agent.runtime import configured_python

from .base import Backend, BackendTask, PreparedTask


def prepare_ase_neb(task: BackendTask) -> PreparedTask:
    reactant = task.inputs["reactant"]
    product = task.inputs["product"]
    images = task.settings.get("images", "7")
    python = configured_python() or "python"
    return PreparedTask(
        backend="ase_neb",
        node_id=task.node_id,
        command=[str(python), "-m", "ase", "neb", "--images", images, reactant, product],
        input_paths=[reactant, product],
        expected_artifacts=["neb.traj", "neb_summary.json"],
    )


class AseNebBackend(Backend):
    name = "ase_neb"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_ase_neb(task)
