# Remote Execution Contract

`ts_remote` uses OpenSSH/SCP and Torque for remote diagnostics.

## Installation-Owned Policy

`remote.toml` owns SSH host/config, remote root, scheduler commands, queues,
resource ceilings, software commands, activation, scratch policy, and server
environment. A calculation request selects a named profile and resources within
its configured limits.

Use `ts_remote` for read-only diagnostics:

- `status`: SSH connectivity only;
- `doctor`: SSH, scheduler, storage, and registered software;
- `queues`: bounded queue view;
- `nodes`: bounded compute-resource view.

Run `doctor` before the first remote calculation or after configuration changes.
For `ase_neb`, `doctor` additionally imports ASE and the TSPi runner with the
configured Python and executes the configured xTB program's version probe. The
profile is ready only when all three components are available.

## Isolation

Remote directories are derived from workspace identity, ResearchNode, and
intent. The upload manifest binds regular files, sizes, SHA-256, command, profile,
resources, expected artifacts, and submission ID. Remote files provide the
execution copy; collection downloads declared outputs into the local workspace.

## Control Lifecycle

Submit persists pre-effect staging state before calling Torque. Once the
scheduler request begins, transport failure may be ambiguous. Preserve any
known job ID and durable submission record even if later queue/history lookup
fails.

Cancel similarly distinguishes known no-effect, known cancellation, and
ambiguous effect. When a job disappears from the queue, inspect its receipt
and declared outputs to establish what happened.

Inspect may combine durable receipt, scheduler state, program status, and a
bounded declared artifact tail. Collection follows the immutable artifact
manifest and works even when scheduler history is unavailable.

## Verify Results

- Reconcile an unknown submit or cancel result before another control action.
- Resolve remote paths and commands from the installation profile and intent.
- Use `doctor` to check scheduler and software readiness as well as SSH.
- Check program termination and required outputs after scheduler completion.
- Collect outputs, verify them locally, and parse them before recording Observations.
