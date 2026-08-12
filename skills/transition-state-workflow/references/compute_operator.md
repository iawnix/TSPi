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
child receives no raw SSH client, scheduler command, host, or arbitrary command
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
a remote scheduler, Gaussian, or canonical-workspace failure. It is replay-safe
only when no bounded action ran before the interruption.

Remote directory creation and upload are staging operations. A failure there is
recorded as `state=failed`, `error_class=remote_staging_failed`,
`control.effect_attempted=false`, and
`control.retry_disposition=retry_same_submission`; it is not a scheduler
submission ambiguity. The same immutable intent and submission ID may retry,
with append-only `submit_attempt_NNNN_guard.json` and
`submit_attempt_NNNN_result.json` records. Only a failure after the
the remote submission script begins is recorded as `submission_ambiguous` and requires
read-only reconciliation rather than replay. A normal `inspect` may persist an
append-only `submit_reconciliation.json` or `cancel_reconciliation.json` after
the durable server request and job binding match the local intent. These files
become the effective control result without changing the original ambiguous
attempt; a reconciled submit may also rebuild `remote_receipt.json` from the bound
expected-artifact manifest so collection can proceed without scheduler history.

## Semantic Preparation And Generated Intent

The Root Agent selects purpose, method, inputs, settings, attempt kind, and
execution target. It does not create an intent file or generated paths. A Pi
prepare call has this shape:

```json
{
  "operation": "prepare",
  "backend": "gaussian",
  "nodeId": "n012",
  "purpose": "Produce TS/Freq evidence for pred_mode_001.",
  "taskType": "opt_freq",
  "attemptKind": "primary",
  "inputArtifacts": [
    {"inputRole": "gjf", "artifactId": "art_7f2d10e681fc90c6e275af42"}
  ],
  "settings": {},
  "executionTarget": {"kind": "local"},
  "dryRun": true
}
```

Call `ts_workspace_context mode=artifacts` before preparation to obtain eligible
logical IDs and compatible roles. Every backend input role must be bound in
`inputArtifacts`. IDs are derived from the owner node and content digest, so a
same-owner rename keeps the ID while a content change creates a new ID. If one
ID matches multiple same-owner files, the kernel rejects it as ambiguous.
The read-only catalog scans only regular, non-symlink `.gjf`, `.com`, `.xyz`,
`.inp`, and `.json` files under `inputs/`, node `inputs/` or `outputs/`, and
attempt `outputs/`. It is rebuilt on demand and is not another canonical state
file or evidence registry.

Before child creation, the host validates `ts-calculation-request/1` and
materializes an immutable `ts-calculation-intent/2`. It derives:

- `intent_id` and `nodes/<node>/attempts/<intent>/`;
- `validation_scope` from the selected node;
- canonical workspace-relative input refs;
- backend-declared expected artifact names under the attempt output directory;
- `authority=execution_mirror` and transport-specific remote directories.

For the call above, the generated record is equivalent to:

```json
{
  "schema_version": "ts-calculation-intent/2",
  "intent_id": "calc_n012_gaussian_opt_freq_0001",
  "node_id": "n012",
  "purpose": "Produce TS/Freq evidence for pred_mode_001.",
  "validation_scope": "tsfreq",
  "attempt_kind": "primary",
  "recalculation_ref": null,
  "backend": "gaussian",
  "task_type": "opt_freq",
  "input_refs": {"gjf": "nodes/n012/inputs/candidate.gjf"},
  "input_bindings": [
    {
      "input_role": "gjf",
      "artifact_id": "art_7f2d10e681fc90c6e275af42",
      "path": "nodes/n012/inputs/candidate.gjf",
      "sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "owner_node": "n012",
      "source_intent_id": null
    }
  ],
  "settings": {},
  "expected_artifacts": [
    "nodes/n012/attempts/calc_n012_gaussian_opt_freq_0001/outputs/gaussian.out"
  ],
  "execution_target": {"kind": "local"},
  "dry_run": true
}
```

`dry_run=true` supports preparation and inspection workflows but cannot be
submitted or cancelled. Set `dry_run=false` only when the intent is intended
for a later control call. Preparation itself has no remote side effect in
either case.

Attempt kinds:

- `primary`: first operational attempt for the node objective;
- `retry`: technical retry under the same node;
- `recalculation`: method change with a non-null source reference.

Public recalculation reference:

```json
{
  "sourceNode": "n012",
  "sourceIntentId": "calc_n012_gaussian_opt_freq_0001",
  "changedSettings": ["functional", "basis_set"],
  "purpose": "method_robustness"
}
```

The source attempt must exist locally. A recalculation result inherits no
scientific verdict from its source.

## Supported Backends

| Backend | Task types | Input roles | Backend policy |
|---|---|---|---|
| `gaussian` | `sp`, `opt`, `freq`, `opt_freq`, `irc` | `gjf` | `backends/gaussian.md` |
| `xtb` | `sp`, `opt`, `freq`, `opt_freq` | `xyz` | `backends/xtb.md` |
| `xtb` | `scan`, `md` | `xyz`, `control` | `backends/xtb.md` |
| `crest` | `conformer_search` | `xyz` | `backends/crest.md` |
| `ase_neb` | `neb` | `reactant`, `product` | `backends/ase.md` |
| `qbics_dmecp` | `dmecp` | `config` | `backends/qbics.md` |

`backends/rdkit.md` is an internal policy but is not exposed by the compute
operator until a typed RDKit adapter is implemented and tested. Every selected
backend policy is composed with `src/agents/compute/policy.md`.

An intent cannot supply a shell command. `input_refs` and `input_bindings` are
kernel-generated snapshots, not public Pi inputs. Bindings are rechecked during
prepare and immediately before submit; inspect and collect do not require the
original local input to remain present. Gaussian preparation verifies that
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

Remote preparation selects one installation-owned profile and a complete
bounded Torque resource request:

```json
{
  "kind": "remote",
  "profile": "cluster_1w",
  "resources": {
    "queue": "batch",
    "nodes": 1,
    "ncpus": 8,
    "memory": "16gb",
    "walltime": "04:00:00",
    "ngpus": 0,
    "mpiprocs": null,
    "ompthreads": 8
  }
}
```

Hosts, SSH configuration, remote roots, scheduler command paths, software
activation, queue policy, and environment belong to the installation TOML
selected by `TS_REMOTE_CONFIG`. The Agent cannot override them. Old requests
containing a transport selector, host, or remote-root field fail schema
validation.

During prepare, the kernel reads or creates `.agents/workspace-identity.json`
and writes an immutable execution policy into `prepared.json`:

```json
{
  "kind": "remote",
  "authority": "execution_mirror",
  "profile": "cluster_1w",
  "workspace_id": "ws_<24 lowercase hex characters>",
  "remote_dir": "/configured/root/workspaces/ws_<24 lowercase hex characters>/runs/n012/calc_n012_gaussian_opt_freq_0001",
  "resources": {"queue": "batch", "nodes": 1, "ncpus": 8}
}
```

All later operations revalidate this binding. Independently initialized
workspaces cannot collide even when node and intent IDs match. Multiple agents
operating on one workspace share its identity and per-intent control guards.

Configure the profile with one absolute file path:

```bash
export TS_REMOTE_CONFIG=/absolute/path/to/remote.toml
```

Every submit/cancel call runs preflight first and binds the operation, node,
backend, intent ID and digest, profile, remote directory, resources, and
scheduler job ID when available. The Root Agent then creates the request-scoped
child without an interactive approval step. Ambiguous submission or
cancellation is written to an immutable control result and cannot be replayed
automatically. Once the remote submission script is handed to SSH, a transport
failure is ambiguous unless the durable submission record resolves it.

Use `ts_remote_inspect` or `/ts-remote doctor` for connection details,
storage, software, and scheduler health, and use `/ts-remote queues` or
`/ts-remote nodes` for one scheduler view. These diagnostics do not expose
remote mutation tools.

Each backend requires a matching software profile with an allowlisted queue.
The generated Torque script sources the configured activation script, owns the
declared environment, executes only the prepared backend command, and writes a
durable program-status record. Missing or inconsistent registration fails
before scheduler submission.

No remote artifact becomes authoritative before collection and local hash or
parser verification. Collection refuses to overwrite existing local files.
Remote execution captures Gaussian stdout into the single declared `.log`/`.out`
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
