# Compute Operator Contract

`ts_workspace_compute_operator` creates one fresh backend child session for one
bound operation:

- `prepare`: validate and persist a dry-run intent;
- `inspect`: poll status and optionally read one bounded tail;
- `collect`: fetch an allowlisted expected-artifact subset;
- `parse`: run a deterministic parser on a local attempt artifact.

The child has no parent history, general filesystem, shell, workspace mutation,
scientific review, recursive delegation, submit, or cancel tools. It receives
only the selected private backend skill and request-scoped typed tools.

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
  "login_host": "login-a",
  "compute_host": "compute-a",
  "remote_dir": "/remote/project/n012/calc_n012_optfreq_001"
}
```

Host policy:

```bash
export TS_COMPUTE_LOGIN_HOSTS=login-a,login-b
export TS_COMPUTE_COMPUTE_HOSTS=compute-a,compute-b
export TS_COMPUTE_REMOTE_ROOTS=/remote/project-a,/remote/project-b
export TS_COMPUTE_SSH_CONFIG=/absolute/path/to/ssh_config
```

No remote artifact becomes authoritative before collection and local hash or
parser verification. Collection refuses to overwrite existing local files.

## Program And Science Boundary

- remote/process failure -> program failure;
- normal termination -> program success only;
- parser output -> deterministic parser facts only;
- wrong imaginary mode -> evidence for a later mechanism evaluation;
- same-basin displacement -> connectivity evidence;
- missing strict R/P proof -> audit blocker.

The Root Agent verifies primary artifacts, registers evidence through
`ts_workspace`, and opens a mechanism or audit node to interpret it.
