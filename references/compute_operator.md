# Compute Operator Contract

`ts_workspace_compute_operator` creates one fresh backend child session for one
bound operation:

- `prepare`: validate and persist a bound intent without executing it;
- `submit`: perform one host-authorized remote submission;
- `inspect`: poll status and optionally read one bounded tail;
- `collect`: fetch an allowlisted expected-artifact subset;
- `cancel`: perform one host-authorized cancellation of the bound job;
- `parse`: run a deterministic parser on a local attempt artifact.

The child has no parent history, general filesystem, shell, workspace mutation,
scientific review, or recursive delegation. It receives only the selected
private backend skill and request-scoped typed tools. For submit/cancel, the
Root host confirms the exact preflight binding before creating a fresh child
with exactly one control tool. The child receives no reusable authorization
object, token, endpoint, or credentials.

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
for a later explicitly authorized control call. Preparation itself has no
remote side effect in either case.

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

| Backend | Task types | Input roles | Private skill |
|---|---|---|---|
| `gaussian` | `sp`, `opt`, `freq`, `opt_freq`, `irc` | `gjf` | `backend-gaussian` |
| `xtb` | `opt` | `xyz` | `backend-xtb` |
| `ase_neb` | `neb` | `reactant`, `product` | `backend-ase` |
| `qbics_dmecp` | `dmecp` | `config` | `backend-qbics` |

`backend-rdkit` is a private skill contract but is not exposed by the compute
operator until a typed RDKit adapter is implemented and tested.

An intent cannot supply a shell command. Gaussian preparation verifies that
the existing route contains flags required by the declared task type; it does
not choose or rewrite the route.

## Local Authority

Every v2 attempt is self-contained:

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

Legacy `ts-calculation-intent/1` and its split `inputs/remote/outputs`
directories remain readable.

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

Legacy remote intents without `transport` are treated as SSH. SSH host and path
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

The MCP endpoint, bearer token, and timeout are never intent data:

```bash
export TS_CLUSTER_MCP_URL=https://cluster.example/mcp
export TS_CLUSTER_MCP_TOKEN='<at-least-32-random-ascii-characters>'
export TS_CLUSTER_MCP_TIMEOUT=60
```

Do not place tokens, passwords, API keys, authorization values, or
`TS_CLUSTER_MCP_*` settings in `execution.environment`; validation rejects
those keys. Cluster software setup belongs in server policy or non-secret
execution variables.

Every submit/cancel call runs preflight first. The Pi host confirmation shows
operation, node, backend, intent ID and digest, transport, target, resources,
and the bound scheduler job ID when available. A headless host or user denial
stops before child creation. Ambiguous submission or cancellation is written to
an immutable control result and cannot be automatically replayed. An exclusive
control guard is written before the first remote side effect; a guard without a
final result means the host was interrupted and requires manual reconciliation.
For MCP `submit`, `inspect`, `collect`, and `cancel`, intent binding is followed
by a read-only `cluster_capabilities` probe before confirmation or child
creation. A failed probe stops the operation with a classified, redacted error.
Use `ts_workspace_mcp_status` or `/ts-mcp doctor` for details and `/ts-mcp
queues` for the read-only scheduler queue list. These diagnostics never expose
raw MCP mutation tools.
MCP submission returns its scheduler ID immediately. SSH cancellation requires
one prior `inspect` so the confirmation and remote kill are both bound to the
observed PID; a changed PID is rejected remotely before signaling a process.

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
