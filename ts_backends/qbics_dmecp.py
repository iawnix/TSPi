"""QBICS dMECP candidate command preparation."""

from __future__ import annotations

from .base import Backend, BackendTask, PreparedTask


def prepare_qbics_dmecp(task: BackendTask) -> PreparedTask:
    config = task.inputs["config"]
    return PreparedTask(
        backend="qbics_dmecp",
        act_id=task.act_id,
        command=["qbics", "dmecp", config],
        input_paths=[config],
        expected_artifacts=["dmecp_candidate.xyz", "dmecp_summary.json"],
    )


class QbicsDmecpBackend(Backend):
    name = "qbics_dmecp"

    def prepare(self, task: BackendTask) -> PreparedTask:
        return prepare_qbics_dmecp(task)
