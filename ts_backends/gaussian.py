"""Gaussian TS/Freq command preparation."""

from __future__ import annotations

from .base import BackendTask, PreparedTask


def prepare_gaussian(task: BackendTask) -> PreparedTask:
    gjf = task.inputs["gjf"]
    output = task.settings.get("output", "gaussian.out")
    return PreparedTask(
        backend="gaussian",
        node_id=task.node_id,
        command=["g16", gjf],
        input_paths=[gjf],
        expected_artifacts=[output],
    )
