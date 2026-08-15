# Deterministic Compute Tools

`ts_compute` executes one typed action selected by the Root Agent. It starts no
child model and cannot choose a method, modify a prepared intent, record a
scientific Observation, or update a Claim.

## Contents

- [Discover Inputs](#discover-inputs)
- [Prepare](#prepare)
- [Submit And Inspect](#submit-and-inspect)
- [Collect And Parse](#collect-and-parse)
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

## Prepare

A prepare request binds:

```json
{
  "operation": "prepare",
  "backend": "gaussian",
  "actId": "act_1",
  "purpose": "Optimize and characterize one TS candidate.",
  "taskType": "opt_freq",
  "attemptKind": "primary",
  "inputArtifacts": [
    {"inputRole": "structure", "artifactId": "art_..."}
  ],
  "settings": {"method": "M062X", "basis": "6-31G(d)"},
  "executionTarget": {
    "kind": "remote",
    "profile": "cluster_1w",
    "resources": {
      "queue": "batch", "nodes": 1, "ncpus": 8,
      "memory": "16gb", "walltime": "24:00:00", "ngpus": 0
    }
  },
  "dryRun": false
}
```

The host resolves input paths and digests, allocates the intent, derives
expected artifacts, and writes `ts-calculation-intent/4` under
`acts/<act_id>/attempts/<intent_id>/`. Do not construct those values.

`dryRun=true` prepares and validates only. It cannot later be submitted as a
remote effect unless its typed contract permits that use.

## Submit And Inspect

Use the exact `backend`, `actId`, and `intentId` returned by prepare:

```json
{"operation":"submit","backend":"gaussian","actId":"act_1","intentId":"calc_..."}
```

Submit revalidates the immutable intent digest, stages the manifest, and issues
one scheduler request. Never call submit twice for the same uncertain control.

Inspect changed or terminal work:

```json
{
  "operation":"inspect",
  "backend":"gaussian",
  "actId":"act_1",
  "intentId":"calc_...",
  "tailArtifact":"gaussian.out",
  "tailLines":80
}
```

Tail is restricted to declared artifact basenames and at most 500 lines.
Scheduler status, program status, and output availability are separate fields.

## Collect And Parse

Collect all declared outputs or an explicit allowed subset:

```json
{
  "operation":"collect",
  "backend":"gaussian",
  "actId":"act_1",
  "intentId":"calc_...",
  "artifacts":["gaussian.out","program_status.json"]
}
```

Collection verifies the immutable remote manifest and downloads into the Act's
local attempt tree. It does not depend on Torque history.

Parse one Kernel-bound local artifact:

```json
{
  "operation":"parse",
  "backend":"gaussian",
  "actId":"act_1",
  "intentId":"calc_...",
  "artifactRef":"acts/act_1/attempts/calc_.../outputs/remote/gaussian.out"
}
```

Parser facts are structured operational output. Verify their source artifacts,
then record individual semantic Observations through a Decision.

## Cancel

Cancel only a bound remote intent:

```json
{"operation":"cancel","backend":"gaussian","actId":"act_1","intentId":"calc_..."}
```

Known success is idempotent. An ambiguous cancel is not safe to replay without
reconciliation.

## Retry And Recalculation

Use `attemptKind=retry` only when the same immutable scientific intent can be
replayed and the typed prior result proves no external effect occurred. Use
`attemptKind=recalculation` when settings or purpose change and provide:

```json
{
  "sourceAct":"act_1",
  "sourceIntentId":"calc_...",
  "changedSettings":["method"],
  "purpose":"method_robustness"
}
```

Preserve the previous attempt. A new method or scientific objective may warrant
a new ResearchAct rather than only a recalculation record.

## Result Authority

The typed action result distinguishes `completed`, `failed`, and `unknown`,
plus whether an external effect was attempted and whether retry is safe. A
returned JSON object is not proof of action success. Program failure is not
automatically Claim contradiction, and parser failure is not program failure.
