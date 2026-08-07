# Compute Operator Contract

`ts_subagent_compute` creates one fresh backend child session for one
bound operation:

- `prepare`: validate and persist a bound intent without executing it;
- `submit`: perform one pre-bound remote submission;
- `inspect`: poll status and optionally read one bounded tail;
- `collect`: fetch an allowlisted expected-artifact subset;
- `cancel`: perform one pre-bound cancellation of the bound job;
- `parse`: run a deterministic parser on a local attempt artifact.

`collect` remains one child-tool call, but it does not query the scheduler or
require that a finished job remain visible in scheduler history. Before
download, the shared control layer binds the immutable submit result, durable
receipt, job ID, remote directory, intent digest, and expected-artifact
manifest. It then downloads only the bound artifact names without overwrite.
An observed local terminal program status is preserved; otherwise collection
uses `program_status=not_run` until a deterministic local parser establishes
the program outcome.

The child has no parent history, general filesystem, shell, workspace mutation,
scientific review, or recursive delegation. It receives only the selected
private backend skill and request-scoped typed tools. For submit/cancel, the
Root Agent validates the exact preflight binding before creating a fresh child
with exactly one control tool. No interactive approval step is required. The
child receives no raw MCP client, endpoint, credentials, or arbitrary command
surface.

The child supplies only an operational summary and limitations. The host
deterministically builds the validated report from typed action results,
including `outcome=success|partial|failure|not_run`, facts, artifact refs,
program state, payload, and provenance. This operator execution outcome is not
the calculation's program outcome. A typed tool exception is journaled as
`action_status=failed`, `state=unknown`, and `program_status=not_run` before the
error returns to the child. An ambiguous submit/cancel is instead
`action_status=unknown` and produces `outcome=partial`. For `inspect`, a failed
status action plus a successful bounded tail is `outcome=partial`. Remote tail
text may be summarized as a limitation, but it does not become a scientific
fact or local artifact ref.

Facts use one shared vocabulary across typed actions and wrapper reports:
`compute_preparation`, `submission`, `inspection`, `collection`,
`cancellation`, `program_status`, and `parser`. Legacy aliases are normalized
only at the report parse boundary. If an action succeeded but report
serialization failed, the journal records
`failure_class=report_serialization_failed_after_action` and
`retry_safe=false`; this is distinct from an action that never ran and from a
remote program failure. An upstream API/SSE interruption such as `408 stream
disconnected before completion` is recorded under
`failure_domain=upstream_model_api` and `failure_stage=model_stream`, never as
an MCP, scheduler, Gaussian, or canonical-workspace failure. It is replay-safe
only when no bounded action ran before the interruption.

MCP directory creation and upload are staging operations. A failure there is
recorded as `state=failed`, `error_class=mcp_staging_failed`,
`control.effect_attempted=false`, and
`control.retry_disposition=retry_same_submission`; it is not a scheduler
submission ambiguity. The same immutable intent and submission ID may retry,
with append-only `submit_attempt_NNNN_guard.json` and
`submit_attempt_NNNN_result.json` records. Only a failure after the
`ts_submit_job` call begins is recorded as `submission_ambiguous` and requires
read-only reconciliation rather than replay. A normal `inspect` may persist an
append-only `submit_reconciliation.json` or `cancel_reconciliation.json` after
the durable server request and job binding match the local intent. These files
become the effective control result without changing the original ambiguous
attempt; a reconciled submit may also rebuild `mcp_receipt.json` from the bound
expected-artifact manifest so collection can proceed without scheduler history.

## Calculation Intent V2

The Root Agent selects purpose, method, scope, and execution target before
delegation.

```json
{
  "schema_version": "ts-calculation-intent/2",
  "intent_id": "calc_n012_optfreq_001",
  "node_id": "n012",
  "purpose": "Produce TS/Freq evidence for pred_mode_001.",
  "validation_scope": "tsfreq",
  "attempt_kind": "primary",
  "recalculation_ref": null,
  "backend": "gaussian",
  "task_type": "opt_freq",
  "input_refs": {
    "gjf": "nodes/n012/inputs/candidate.gjf"
  },
  "settings": {},
  "expected_artifacts": [
    "nodes/n012/attempts/calc_n012_optfreq_001/outputs/candidate.log"
  ],
  "execution_target": {"kind": "local"},
  "dry_run": true
}
```

`validation_scope` is null for candidate-search calculations and must match a
validation node when the selected node is a validation node.

`dry_run=true` supports preparation and inspection workflows but cannot be
submitted or cancelled. Set `dry_run=false` only when the intent is intended
for a later control call. Preparation itself has no remote side effect in
either case.

Attempt kinds:

- `primary`: first operational attempt for the node objective;
- `retry`: technical retry under the same node;
- `recalculation`: method change with a non-null source reference.

Example recalculation reference:

```json
{
  "source_node": "n012",
  "source_intent_id": "calc_n012_optfreq_001",
  "changed_settings": ["functional", "basis_set"],
  "purpose": "method_robustness"
}
```

The source attempt must exist locally. A recalculation result inherits no
scientific verdict from its source.

## Supported Backends

| Backend | Task types | Input roles | Backend policy |
|---|---|---|---|
| `gaussian` | `sp`, `opt`, `freq`, `opt_freq`, `irc` | `gjf` | `backends/gaussian.md` |
| `xtb` | `opt` | `xyz` | `backends/xtb.md` |
| `ase_neb` | `neb` | `reactant`, `product` | `backends/ase.md` |
| `qbics_dmecp` | `dmecp` | `config` | `backends/qbics.md` |

`backends/rdkit.md` is an internal policy but is not exposed by the compute
operator until a typed RDKit adapter is implemented and tested. Every selected
backend policy is composed with `src/agents/compute/policy.md`.

An intent cannot supply a shell command. Gaussian preparation verifies that
the existing route contains flags required by the declared task type; it does
not choose or rewrite the route. Backend input roles are exact: Gaussian
accepts only `input_refs.gjf`; unexpected roles such as `source_xyz` are
rejected with explicit `missing=[...]` and `unexpected=[...]` diagnostics.
The public Pi `parse` schema requires both `intentId` and `artifactRef` before
the call reaches the adapter.

## Local Authority

Every attempt is self-contained:

```text
nodes/<node>/attempts/<intent>/
├── intent.json
├── prepared.json
├── status.json
├── submit_guard.json / submit_result.json
├── cancel_guard.json / cancel_result.json
└── outputs/
    ├── collected/
    ├── parsed/
    └── calculation_result.json
```

These are operational artifacts, not canonical scientific state. `ts_web`
shows their state separately from node lifecycle, hypothesis status, and audit
status.

## Remote Execution Mirror

Remote targets must be allowlisted and explicitly non-authoritative:

```json
{
  "kind": "remote",
  "authority": "execution_mirror",
  "transport": "ssh",
  "login_host": "login-a",
  "compute_host": "compute-a",
  "remote_dir": "/remote/project/n012/calc_n012_optfreq_001"
}
```

Remote intents without an explicit `transport` are rejected. SSH host and path
policy remains environment-owned through `TS_COMPUTE_*`.

MCP targets use a workspace-relative cluster directory and a complete resource
shape:

```json
{
  "kind": "remote",
  "authority": "execution_mirror",
  "transport": "mcp",
  "remote_dir": "runs/n012/calc_n012_optfreq_001",
  "execution": {
    "queue": "workq",
    "nodes": 1,
    "ncpus": 8,
    "memory": "16gb",
    "walltime": "04:00:00",
    "ngpus": 0,
    "mpiprocs": null,
    "ompthreads": 8,
    "host": null,
    "place": null,
    "environment": {},
    "gpu_devices": []
  }
}
```

The intent value above is a logical directory, not the final principal-relative
path. During prepare, the compute kernel reads or creates the persistent
`.agents/workspace-identity.json` record and writes this immutable binding into
the attempt's `prepared.json`:

```json
{
  "namespace_version": "ts-mcp-workspace/1",
  "workspace_id": "ws_<24 lowercase hex characters>",
  "requested_remote_dir": "runs/n012/calc_n012_optfreq_001",
  "remote_dir": "workspaces/ws_<24 lowercase hex characters>/runs/n012/calc_n012_optfreq_001",
  "submission_id": "tsjob_<workspace-bound value>"
}
```

All later MCP operations use the prepared binding rather than reconstructing a
path from the current process or Pi session. Independently initialized
workspaces therefore cannot collide when they use the same principal and
intent ID. Multiple agents intentionally operating on one workspace share the
same identity and the same per-intent atomic control guards. Prepared records
without `ts-mcp-workspace/1`, a workspace identity, the workspace-bound
directory, or the matching submission ID are rejected.

The MCP endpoint, bearer token, and timeout are never intent data:

```bash
export TS_CLUSTER_MCP_URL=https://cluster.example/mcp
export TS_CLUSTER_MCP_TOKEN='<at-least-32-random-ascii-characters>'
export TS_CLUSTER_MCP_TIMEOUT=60
export TS_CLUSTER_MCP_DIAGNOSTIC_TIMEOUT=15
```

`TS_CLUSTER_MCP_TIMEOUT` applies to calculation and control calls.
`TS_CLUSTER_MCP_DIAGNOSTIC_TIMEOUT` is a separate per-component bound for
read-only readiness probes. A diagnostic timeout means readiness is unknown and
does not imply that configuration, authentication, or the MCP protocol failed.
No remote action has occurred at that point.

Do not place tokens, passwords, API keys, authorization values, or
`TS_CLUSTER_MCP_*` settings in `execution.environment`; validation rejects
those keys. Cluster software setup belongs in server policy or non-secret
execution variables.

Every submit/cancel call runs preflight first and binds the operation, node,
backend, intent ID and digest, transport, target, resources, and scheduler job
ID when available. The Root Agent then creates the request-scoped child without
an interactive approval step. Ambiguous submission or cancellation is written
to an immutable control result and cannot be automatically replayed. An
exclusive control guard is written before the first remote side effect; a guard
without a final result means the host was interrupted and requires manual
reconciliation.
For MCP `submit`, `inspect`, `collect`, and `cancel`, intent binding is followed
by a read-only `cluster_capabilities` probe before child creation. A failed
probe stops the operation with a classified, redacted error.
Use `ts_mcp_inspect` or `/ts-mcp doctor` for connection details,
`/ts-mcp queues` or `/ts-mcp nodes` for one scheduler view, and `/ts-mcp
cluster` for combined cluster status. Use these read-only diagnostics only for
an intent whose selected transport is MCP. Do not change from MCP to SSH or from
SSH to MCP automatically after a failure; report the failure and require an
explicit transport decision. Label the source when comparing transports. These
diagnostics never expose raw MCP mutation tools.
For `backend=gaussian`, submit additionally requires a same-name server
software profile with an existing activation script and an allowlisted target
queue. The server sources that profile before executing the manifest-bound
runner. The runner owns a private random `GAUSS_SCRDIR`, refuses output
overwrite, and removes scratch on exit. Missing or inconsistent registration
fails before child creation and is checked again before scheduler access.
MCP submission returns its scheduler ID immediately. SSH cancellation requires
one prior `inspect` so the preflight binding and remote kill are both bound to
the observed PID; a changed PID is rejected remotely before signaling a process.

Host policy:

```bash
export TS_COMPUTE_LOGIN_HOSTS=login-a,login-b
export TS_COMPUTE_COMPUTE_HOSTS=compute-a,compute-b
export TS_COMPUTE_REMOTE_ROOTS=/remote/project-a,/remote/project-b
export TS_COMPUTE_SSH_CONFIG=/absolute/path/to/ssh_config
```

No remote artifact becomes authoritative before collection and local hash or
parser verification. Collection refuses to overwrite existing local files.
The transport captures Gaussian stdout into the single declared `.log`/`.out`
artifact and xTB stdout into `xtb.out`; other backend stdout/stderr remain
bounded operational logs for inspection.

## Program And Science Boundary

- remote/process failure -> program failure;
- normal termination -> program success only;
- parser output -> deterministic parser facts only;
- wrong imaginary mode -> evidence for a later mechanism evaluation;
- same-basin displacement -> connectivity evidence;
- missing strict R/P proof -> audit blocker.

The Root Agent verifies primary artifacts, registers evidence through
`ts_workspace`, and opens a mechanism or audit node to interpret it.
