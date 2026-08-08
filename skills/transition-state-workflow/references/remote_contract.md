# Remote Contract

`ts_remote` manages generic remote job lifecycle through
`ts_remote.job_lifecycle`:

- stage files;
- submit commands asynchronously;
- poll scheduler or process state;
- tail logs;
- fetch artifacts;
- kill jobs when requested;
- record receipts.

Remote helpers do not parse chemistry and do not write workspace verdicts.
Receipts and status records stay under the calculation attempt as operational
provenance. They are never evidence by themselves.

For scheduler-backed execution, `ts_remote.mcp` talks to the bundled
`cluster_mcp` service through `ts-cluster-job/1`. Use it for manifest-bound
transfer, submission, status, collection, and explicit cancellation. Read
`cluster_mcp.md` before configuring scopes or transport. Raw MCP tools remain a
host implementation boundary and are not registered into Pi agent sessions.
The Root compute operator may create one request-scoped submit or cancel wrapper
after exact intent, digest, target, and job binding. No interactive confirmation
is required.

The public semantic request selects `execution_target.transport=ssh|mcp`. SSH
provides an absolute allowlisted `remote_root`; MCP provides complete scheduler
resources. The compute kernel appends the selected node and generated intent ID
to create an SSH `remote_dir`, or creates `runs/<node>/<intent>` for MCP. New
MCP preparations bind that logical path to
`workspaces/<workspace_id>/<remote_dir>` using the persistent
non-scientific identity in `.agents/workspace-identity.json`. The resolved path
and workspace-bound submission ID are persisted in `prepared.json`; later
operations do not derive them from the Pi process. Prepared MCP records without
the namespace marker or matching workspace binding are rejected. Remote targets
without an explicit `transport` are also rejected. MCP
connection URL, token, and timeout come only from
`TS_CLUSTER_MCP_URL`, `TS_CLUSTER_MCP_TOKEN`, and `TS_CLUSTER_MCP_TIMEOUT`.
Read-only probes may additionally use `TS_CLUSTER_MCP_DIAGNOSTIC_TIMEOUT`; it
does not change calculation or control-call timeouts.
SSH cancellation requires a previously inspected PID and verifies that the
remote PID file still matches before sending a signal.

Backends expose calculation intent as `PreparedTask` data: command, input paths,
environment, and expected artifacts. xTB, ASE-NEB, and other local adapters feed
that data into `ts_remote.job_lifecycle.config_from_prepared_task()` when the
same calculation needs to run remotely. Backend modules should not duplicate
SSH staging, asynchronous launch, polling, fetch, or kill logic.

Gaussian remote execution is implemented by the internal adapter
`ts_remote.gaussian`. It converts `RemoteGaussianConfig` into the same generic
`RemoteJobConfig`, stages `.gjf` plus extra files such as `%oldchk`/checkpoint
inputs, and uses `ts_remote.job_lifecycle.submit_async()` for asynchronous
submission. Do not expose a standalone Gaussian remote-runner script as part of
the public workflow surface. The generated compute-side runner must source
Gaussian profiles with unset-variable protection because cluster profiles may
read variables such as `LD_LIBRARY64_PATH` before defining them.
Asynchronous launch should also protect each remote run directory against
duplicate submission: reject a second launch when the recorded PID is still
active, record a per-run identifier in remote status/metadata, and use a
scratch subdirectory unique to that run rather than a process-shared Gaussian
scratch root.
