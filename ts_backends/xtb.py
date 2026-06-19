"""xTB candidate-generation command preparation."""

from __future__ import annotations

from .base import BackendTask, PreparedTask


def prepare_xtb_opt(task: BackendTask) -> PreparedTask:
    xyz = task.inputs["xyz"]
    charge = task.settings.get("charge", "0")
    uhf = task.settings.get("uhf", "0")
    return PreparedTask(
        backend="xtb",
        node_id=task.node_id,
        command=["xtb", xyz, "--opt", "--chrg", charge, "--uhf", uhf],
        input_paths=[xyz],
        expected_artifacts=["xtbopt.xyz", "xtb.out"],
    )
