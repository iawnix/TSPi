# Compute Subagent And Typed Actions

`ts_calc` delegates one bounded operational lifecycle. Root chooses
the chemistry, method, ResearchNode, inputs, parameters, and execution target. The
host resolves the immutable intent and exposes only pre-bound zero-argument
tools to the isolated child.

The public lifecycle is closed:

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

There is no public `prepare`, `submit`, `status`, `tail`, `collect`, or `parse`
operation. Those are private deterministic actions. The child cannot change
their arguments, call another tool, or choose a scientific method.

## Contents

- [Discover Inputs](#discover-inputs)
- [Launch](#launch)
- [Inspect](#inspect)
- [Finalize](#finalize)
- [Cancel](#cancel)
- [Retry And Recalculation](#retry-and-recalculation)
- [Result Authority](#result-authority)

## Discover Inputs

Read:

```text
ts_state mode=artifacts
ts_state mode=capabilities capabilityKind=compute
```

The artifact catalog supplies logical `art_...` IDs, paths, SHA-256, owners,
and compatible roles. The capability catalog supplies the capability ID/version,
parameter shape, input/output roles, and parser contract. It does not prove live
software or remote health.

If a fresh workspace has no suitable input, start an open ResearchNode. Use
`ts_seed` for one connected SMILES or `ts_import` for
bounded Gaussian, XYZ, or xTB control text. The host returns the logical ID;
callers never create an `art_*` value or workspace path.

## Launch

Launch accepts the complete semantic request and remote execution target:

```json
{
  "operation": "launch",
  "nodeId": "node_1",
  "purpose": "Optimize and characterize one TS candidate.",
  "capability": "gaussian.opt_freq",
  "capabilityVersion": "1",
  "attemptKind": "primary",
  "inputArtifacts": [
    {"inputRole": "gjf", "artifactId": "art_..."}
  ],
  "parameters": {"method": "M062X", "basis": "6-31G(d)"},
  "executionTarget": {
    "kind": "remote",
    "profile": "cluster_1w",
    "resources": {
      "queue": "batch", "nodes": 1, "ncpus": 8,
      "memory": "16gb", "walltime": "24:00:00", "ngpus": 0
    }
  }
}
```

Before the child starts, the host creates and validates a new
`ts-calculation-intent/7`, binds the current Node contract, resolves paths and
digests, allocates expected artifacts, and freezes the scientific and execution
bindings. Older intent schemas are unsupported and are not converted. The
child then calls prepare and, only after known prepare success, submit. Submit
is single-use. An unknown effect ends the lifecycle with reconciliation
required.

Keep the owning ResearchNode open until the Attempt reaches `parsed`, `failed`,
or `stopped` and Root has recorded any needed scientific interpretation.
`completed` only says the scheduler/program ended; collection and parsing are
still pending. `collected` still requires parsing. A created or prepared intent
has made no external change and does not by itself prevent abandoning the Node.

The public launch path requires a configured `remote` execution target. A
`local` target is available only to the deterministic kernel for `dry_run=true`
preparation and parsing of an output that already exists; it never starts a
local Gaussian, xTB, or scheduler process. `submit`, `status`, `tail`,
`collect`, and `cancel` always require a prepared remote target.

## Inspect

Inspect polls one bound intent and may read one declared artifact tail:

```json
{
  "operation": "inspect",
  "nodeId": "node_1",
  "intentId": "calc_1",
  "tailArtifact": "gaussian.out",
  "tailLines": 80
}
```

Status always runs first. The child may submit the result immediately or call
tail once when diagnostics are useful. Tail is restricted to declared artifact
basenames and at most 500 lines. Scheduler state, program state, and output
availability remain separate fields.

## Finalize

Finalize collects an allowed output set and parses one collected artifact:

```json
{
  "operation": "finalize",
  "nodeId": "node_1",
  "intentId": "calc_1",
  "artifacts": ["gaussian.out", "program_status.json"],
  "artifactRef": "nodes/node_1/attempts/calc_1/outputs/remote/gaussian.out"
}
```

Parse runs only after collection completes. Collection verifies the immutable
remote manifest and does not depend on Torque history. Parser facts are
operational output. `program_status` reports whether the executable reached its
normal terminus; `task_validation` separately reports whether the requested
capability produced its required outputs and convergence evidence. A normally
terminated program can therefore have `task_validation.status=incomplete`.
Root must verify the primary artifacts before recording individual semantic
Observations through a Decision.

For a Node that was closed prematurely by an older runtime, continue inspect and
finalize with the original `nodeId` and `intentId`. Never move or duplicate the
Attempt. Use an open dependent recovery Node to record directly verified
Observations with the original artifacts and digests; the parser-candidate
shortcut intentionally remains restricted to its owning Node.

## Cancel

Cancel targets one bound remote intent:

```json
{"operation":"cancel","nodeId":"node_1","intentId":"calc_1"}
```

The action is single-use. Known success is idempotent. An ambiguous cancel must
be reconciled and is never replayed by the child.

## Retry And Recalculation

Every launch declares `attemptKind`. `primary` forbids a source. Use
`attemptKind=retry` for a new Attempt only when capability, input artifact
digests, and parameters are unchanged. Use `attemptKind=recalculation` when one of
those scientific bindings changes but the calculation still answers the same
Node question and principal deliverable. Both forms cite one source Attempt in
the same Node:

```json
{
  "operation": "launch",
  "nodeId": "node_1",
  "attemptKind": "recalculation",
  "sourceAttempt": {
    "intentId": "calc_1",
    "reason": "Check whether the stationary-point conclusion survives the method change."
  },
  "parameters": {"method": "wB97XD", "basis": "def2SVP"}
}
```

The Kernel derives `changed_fields`; callers do not declare their own diff.
Preserve the source Attempt. A method variation used to answer the same bounded
question is a recalculation. An independent method branch, changed hypothesis,
new endpoint question, or different principal deliverable starts a dependent
ResearchNode and consumes prior outputs through artifact bindings, never through
cross-Node Attempt lineage.

Do not confuse a new retry Attempt with a control-action replay. A typed
pre-effect `retry_same_submission` result permits repeating the same submit
action on the existing intent and allocates no new `calc_*`. A new
`attemptKind=retry` represents a separate execution of the unchanged scientific
intent after that prior lifecycle has ended safely.

## Result Authority

The model fills only `summary` and `limitations` in `ts_compute_result`. The
host derives action outcome, program state, artifacts, facts, provenance, and
reconciliation flags from the typed action journal. A structured tool return is
not proof of remote success. Program failure is not Claim contradiction, and
parser failure is not program failure.

If a submit or cancel action loses its typed client result, it is recorded as
`client_result_unknown` and requires reconciliation. This does not replace the
more precise retryable pre-submit upload result returned by the compute kernel.
