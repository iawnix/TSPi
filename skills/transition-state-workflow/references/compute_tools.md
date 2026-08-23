# Compute Subagent And Typed Actions

`ts_subagent_compute` delegates one bounded operational lifecycle. Root chooses
the chemistry, method, ResearchAct, inputs, settings, and execution target. The
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
ts_workspace_context mode=artifacts
ts_workspace_context mode=compute_capabilities
```

The artifact catalog supplies logical `art_...` IDs, paths, SHA-256, owners,
and compatible roles. The capability catalog supplies backend/task/settings
shape. It does not prove live software or remote health.

If a fresh workspace has no suitable input, start an open ResearchAct. Use
`ts_structure_seed` for one connected SMILES or `ts_artifact_import` for
bounded Gaussian, XYZ, or xTB control text. The host returns the logical ID;
callers never create an `art_*` value or workspace path.

## Launch

Launch accepts the complete semantic request and remote execution target:

```json
{
  "operation": "launch",
  "backend": "gaussian",
  "actId": "act_1",
  "purpose": "Optimize and characterize one TS candidate.",
  "taskType": "opt_freq",
  "attemptKind": "primary",
  "inputArtifacts": [
    {"inputRole": "gjf", "artifactId": "art_..."}
  ],
  "settings": {"method": "M062X", "basis": "6-31G(d)"},
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

Before the child starts, the host creates and validates
`ts-calculation-intent/4`, resolves paths and digests, allocates expected
artifacts, and freezes the execution binding. The child then calls prepare and,
only after known prepare success, submit. Submit is single-use. An unknown
effect ends the lifecycle with reconciliation required.

## Inspect

Inspect polls one bound intent and may read one declared artifact tail:

```json
{
  "operation": "inspect",
  "backend": "gaussian",
  "actId": "act_1",
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
  "backend": "gaussian",
  "actId": "act_1",
  "intentId": "calc_1",
  "artifacts": ["gaussian.out", "program_status.json"],
  "artifactRef": "acts/act_1/attempts/calc_1/outputs/remote/gaussian.out"
}
```

Parse runs only after collection completes. Collection verifies the immutable
remote manifest and does not depend on Torque history. Parser facts are
operational output. Root must verify the primary artifacts before recording
individual semantic Observations through a Decision.

## Cancel

Cancel targets one bound remote intent:

```json
{"operation":"cancel","backend":"gaussian","actId":"act_1","intentId":"calc_1"}
```

The action is single-use. Known success is idempotent. An ambiguous cancel must
be reconciled and is never replayed by the child.

## Retry And Recalculation

Use `attemptKind=retry` on a new launch only when the same immutable scientific
intent can be replayed and the prior typed result proves no external effect was
attempted. Use `attemptKind=recalculation` when settings or purpose change:

```json
{
  "sourceAct": "act_1",
  "sourceIntentId": "calc_1",
  "changedSettings": ["method"],
  "purpose": "method_robustness"
}
```

Preserve the previous attempt. A new method or scientific objective may warrant
a new ResearchAct rather than only a recalculation record.

## Result Authority

The model fills only `summary` and `limitations` in `ts_compute_result`. The
host derives action outcome, program state, artifacts, facts, provenance, and
reconciliation flags from the typed action journal. A structured tool return is
not proof of remote success. Program failure is not Claim contradiction, and
parser failure is not program failure.

If a submit or cancel action loses its typed client result, it is recorded as
`client_result_unknown` and requires reconciliation. This does not replace the
more precise retryable pre-submit upload result returned by the compute kernel.
