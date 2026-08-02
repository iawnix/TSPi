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
Receipts should be stored under `nodes/<node_id>/remote/` and then registered as
evidence or provenance through `ts_workspace`.

For scheduler-backed execution, `ts_remote.mcp` talks to the bundled
`cluster_mcp` service through `ts-cluster-job/1`. Use it for manifest-bound
transfer, submission, status, collection, and explicit cancellation. Read
`cluster_mcp.md` before configuring scopes or transport. Raw MCP tools remain a
host implementation boundary and are not registered into Pi agent sessions.

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
