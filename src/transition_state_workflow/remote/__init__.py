"""Remote transport and synchronization interfaces."""

from transition_state_workflow.remote.openssh import OpenSSHTransport
from transition_state_workflow.remote.sync import build_metadata_sync_plan, execute_sync_plan, verify_sync_plan
from transition_state_workflow.remote.contracts import (
    RemoteCommandResult,
    RemoteTransport,
    RemoteWorkspace,
    SyncEntry,
    SyncPlan,
)

__all__ = [
    "OpenSSHTransport",
    "RemoteCommandResult",
    "RemoteTransport",
    "RemoteWorkspace",
    "SyncEntry",
    "SyncPlan",
    "build_metadata_sync_plan",
    "execute_sync_plan",
    "verify_sync_plan",
]
