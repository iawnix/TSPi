"""Remote transport and synchronization interfaces."""

from transition_state_workflow.remote.gaussian_monitor import (
    DEFAULT_FETCH_PATTERNS,
    RemoteNodeLayout,
    fetch_list_command,
    status_command,
    tail_command,
)
from transition_state_workflow.remote.gaussian_runner import (
    GaussianRunLayout,
    build_run_layout,
    checkpoint_name,
    infer_node_id_from_input,
    nested_compute_ssh_argv,
    remote_runner_text,
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
    "GaussianRunLayout",
    "RemoteCommandResult",
    "RemoteNodeLayout",
    "RemoteTransport",
    "RemoteWorkspace",
    "SyncEntry",
    "SyncPlan",
    "build_metadata_sync_plan",
    "build_run_layout",
    "checkpoint_name",
    "execute_sync_plan",
    "fetch_list_command",
    "infer_node_id_from_input",
    "nested_compute_ssh_argv",
    "remote_runner_text",
    "status_command",
    "sync_cli_main",
    "tail_command",
    "verify_sync_plan",
]
