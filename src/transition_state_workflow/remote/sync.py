"""Explicit synchronization planning and execution for remote workspaces."""

from __future__ import annotations

from pathlib import Path

from transition_state_workflow.remote.contracts import RemoteTransport, RemoteWorkspace, SyncEntry, SyncPlan

DEFAULT_SYNC_PATTERNS = (
    "manifest.json",
    "tree.json",
    "mechanism_model.json",
    "knowledge_base.md",
    "evidence_registry.json",
    "pathway_model.json",
)


def build_metadata_sync_plan(workspace: RemoteWorkspace, patterns: tuple[str, ...] = DEFAULT_SYNC_PATTERNS) -> SyncPlan:
    """Build a conservative metadata sync plan for explorer mirrors."""

    entries = tuple(
        SyncEntry(
            remote_path=f"{workspace.remote_root.rstrip('/')}/{pattern}",
            local_path=workspace.local_mirror / pattern,
            required=False,
        )
        for pattern in patterns
    )
    return SyncPlan(workspace=workspace, entries=entries)


def execute_sync_plan(plan: SyncPlan, transport: RemoteTransport) -> tuple[SyncEntry, ...]:
    """Download every entry in a sync plan and return attempted entries."""

    for entry in plan.entries:
        entry.local_path.parent.mkdir(parents=True, exist_ok=True)
        transport.download(entry.remote_path, entry.local_path)
    return plan.entries


def verify_sync_plan(plan: SyncPlan) -> tuple[str, ...]:
    """Return missing required local files after a sync attempt."""

    return tuple(str(entry.local_path) for entry in plan.entries if entry.required and not entry.local_path.exists())
