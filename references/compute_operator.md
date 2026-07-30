# Compute Operator Contract

The Pi root surface contains one `ts_workspace_compute_operator`. Each call
creates a fresh in-memory child session and privately binds only the typed tools
needed for one operation:

- `prepare`: validate and persist one dry-run intent;
- `inspect`: poll status, then optionally read one bounded log tail;
- `collect`: fetch an allowlisted expected-artifact subset;
- `parse`: run the deterministic parser for one selected-node output.

The child has no parent history, general filesystem tools, shell, workspace
mutation tools, scientific review tools, recursive delegation, submit, or
cancel capability.

## Calculation Intent

The Root Agent chooses the scientific purpose and method before delegation.
Write a `ts-calculation-intent/1` JSON object, for example:

```json
{
  "schema_version": "ts-calculation-intent/1",
  "intent_id": "calc_n012_optfreq_001",
  "node_id": "n012",
  "purpose": "Evaluate the selected candidate for pred_mode_001.",
  "evidence_layer": "tsfreq",
  "backend": "gaussian",
  "task_type": "opt_freq",
  "input_refs": {
    "gjf": "nodes/n012/inputs/candidate.gjf"
  },
  "settings": {},
  "expected_artifacts": [
    "nodes/n012/outputs/candidate.log"
  ],
  "execution_target": {
    "kind": "local"
  },
  "dry_run": true
}
```

The current operator rejects `dry_run=false`. Commands are derived from an
allowlisted backend; an intent cannot supply a shell command.

Supported backend/task/input-role combinations:

| Backend | Task types | Required input roles |
|---|---|---|
| `gaussian` | `sp`, `opt`, `freq`, `opt_freq`, `irc` | `gjf` |
| `xtb` | `opt` | `xyz` |
| `ase_neb` | `neb` | `reactant`, `product` |
| `qbics_dmecp` | `dmecp` | `config` |

Gaussian preparation checks that the input route contains the operation flags
required by the declared task type. It does not choose or rewrite the route.

## Remote Allowlist

Remote targets are disabled unless all applicable host policy variables are
set:

```bash
export TS_COMPUTE_LOGIN_HOSTS=login-a,login-b
export TS_COMPUTE_COMPUTE_HOSTS=compute-a,compute-b
export TS_COMPUTE_REMOTE_ROOTS=/remote/project-a,/remote/project-b
export TS_COMPUTE_SSH_CONFIG=/absolute/path/to/ssh_config  # optional
```

Hosts require exact matches. `remote_dir` must be an absolute POSIX path under
one configured root. Model-supplied authorization strings are not accepted.

## Durable Artifacts

For `intent_id=calc_x`, operational records live under the selected node:

```text
nodes/<node>/inputs/calculations/calc_x.json
nodes/<node>/remote/calculations/calc_x/prepared.json
nodes/<node>/remote/calculations/calc_x/status.json
nodes/<node>/outputs/calculations/calc_x/collected/
nodes/<node>/outputs/calculations/calc_x/parsed/
nodes/<node>/outputs/calculations/calc_x/calculation_result.json
```

These records are not canonical scientific state. `ts_web` displays them as a
separate calculation state alongside, but never merged with, node lifecycle and
`claim_verdict`.

## Interpretation Boundary

- remote/process failure -> program failure;
- normal termination -> program completion only;
- Gaussian parser output -> deterministic parser facts only;
- wrong imaginary mode -> TS/Freq-layer scientific issue;
- same-basin displacement -> connectivity-layer scientific issue;
- missing strict R/P proof -> accepted/pathway audit blocker.

The Root Agent must verify primary artifacts, register evidence through a
decision, and make the scientific judgment. No automatic repair or resubmission
is allowed.
