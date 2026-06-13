"""Remote transport and synchronization interfaces."""

from transition_state_workflow.remote.gaussian_monitor import (
    DEFAULT_FETCH_PATTERNS,
    RemoteNodeLayout,
    fetch_list_command,
    status_command,
    tail_command,
)
from transition_state_workflow.remote.openssh import OpenSSHTransport
from transition_state_workflow.remote.sync_cli import main as sync_cli_main
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
    "DEFAULT_FETCH_PATTERNS",
    "RemoteCommandResult",
    "RemoteNodeLayout",
    "RemoteTransport",
    "RemoteWorkspace",
    "SyncEntry",
    "SyncPlan",
    "build_metadata_sync_plan",
    "execute_sync_plan",
    "fetch_list_command",
    "status_command",
    "sync_cli_main",
    "tail_command",
    "verify_sync_plan",
]
