"""Gaussian TS/Freq command preparation."""

from __future__ import annotations

from .base import Backend, BackendTask, PreparedTask


def prepare_gaussian(task: BackendTask) -> PreparedTask:
    gjf = task.inputs["gjf"]
    output = task.settings.get("output", f"nodes/{task.node_id}/outputs/gaussian.out")
    return PreparedTask(
        backend="gaussian",
        node_id=task.node_id,
        command=["g16", gjf],
        input_paths=[gjf],
        expected_artifacts=[output],
    )


class GaussianBackend(Backend):
    name = "gaussian"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_gaussian(task)
