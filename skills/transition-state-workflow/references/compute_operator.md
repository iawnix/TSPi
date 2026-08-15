# Compute Operator

`ts_subagent_compute` executes one typed action selected by the Root Agent. The
child cannot select a method, change a prepared intent, register Evidence, or
update a Claim.

The registered tool schema is authoritative for call fields. Use
`ts_workspace_context mode=capabilities` for supported backend, task, and input
role combinations. Use this reference for operating semantics and examples.
Do not inspect package source or tests to infer ordinary calls.

Every JSON block below contains the arguments for the named public tool, not an
entire provider API request. Replace example IDs only with values returned by
the workspace tools.

## Contents

- [Discover Inputs And Capabilities](#discover-inputs-and-capabilities)
- [Prepare](#prepare)
- [Submit](#submit)
- [Inspect](#inspect)
- [Collect](#collect)
- [Parse](#parse)
- [Cancel](#cancel)
- [Retry And Recalculation](#retry-and-recalculation)

## Discover Inputs And Capabilities

Read the owning Node's logical artifacts before preparing a calculation:

<!-- ts_workspace_context-example:artifact-discovery -->
```json
{
  "mode": "artifacts",
  "nodeId": "n003"
}
```

When the backend/task/input-role combination is uncertain, read the adapter
catalog:

<!-- ts_workspace_context-example:capabilities -->
```json
{
  "mode": "capabilities"
}
```

An `artifactId` is a returned logical identifier. Do not substitute a source
path, choose a generated filename, or invent an artifact ID.

## Prepare

Preparation writes `ts-calculation-intent/3`, assigns the intent ID and attempt
directory, resolves artifact paths and hashes, generates inputs/scripts, and
binds expected artifacts. It performs no scheduler submission.

Local xTB optimization:

<!-- ts_subagent_compute-example:local-prepare -->
```json
{
  "operation": "prepare",
  "backend": "xtb",
  "nodeId": "n003",
  "purpose": "Optimize the selected candidate geometry before higher-level validation.",
  "taskType": "opt",
  "attemptKind": "primary",
  "inputArtifacts": [
    {
      "inputRole": "xyz",
      "artifactId": "art_0123456789abcdef01234567"
    }
  ],
  "settings": {
    "method": "gfn2",
    "charge": "0",
    "uhf": "0",
    "opt_level": "tight"
  },
  "executionTarget": {
    "kind": "local"
  },
  "dryRun": false
}
```

Remote Gaussian optimization plus frequency calculation:

<!-- ts_subagent_compute-example:remote-prepare -->
```json
{
  "operation": "prepare",
  "backend": "gaussian",
  "nodeId": "n003",
  "purpose": "Optimize the selected transition-state candidate and calculate its harmonic frequencies.",
  "taskType": "opt_freq",
  "attemptKind": "primary",
  "inputArtifacts": [
    {
      "inputRole": "gjf",
      "artifactId": "art_89abcdef0123456701234567"
    }
  ],
  "executionTarget": {
    "kind": "remote",
    "profile": "cluster_1w",
    "resources": {
      "queue": "batch",
      "nodes": 1,
      "ncpus": 8,
      "memory": "16gb",
      "walltime": "04:00:00",
      "ngpus": 0,
      "ompthreads": 8
    }
  },
  "dryRun": false
}
```

Preparation rejects raw source paths, arbitrary command arguments, transport
endpoints, hostnames, remote roots, and request-selected output paths.

## Submit

Use the exact `intentId`, backend, and owning Node returned by preparation:

<!-- ts_subagent_compute-example:submit -->
```json
{
  "operation": "submit",
  "backend": "gaussian",
  "nodeId": "n003",
  "intentId": "calc_n003_gaussian_opt_freq_0001"
}
```

Submit runs exact preflight, stages the immutable manifest, and issues one
bound scheduler request. A structured return is not action success. Preserve
`action_outcome=unknown` for an ambiguous scheduler effect.

## Inspect

Inspect returns bounded scheduler, program, and remote-artifact facts. It is the
only Root operation for status and an optional bounded tail:

<!-- ts_subagent_compute-example:inspect -->
```json
{
  "operation": "inspect",
  "backend": "gaussian",
  "nodeId": "n003",
  "intentId": "calc_n003_gaussian_opt_freq_0001",
  "tailArtifact": "gaussian.out",
  "tailLines": 120
}
```

Use inspect after a meaningful state change or when terminal diagnostics are
needed. Do not poll an unchanged calculation every turn.

## Collect

Collect declared remote artifacts without depending on current scheduler
visibility:

<!-- ts_subagent_compute-example:collect -->
```json
{
  "operation": "collect",
  "backend": "gaussian",
  "nodeId": "n003",
  "intentId": "calc_n003_gaussian_opt_freq_0001",
  "artifacts": [
    "gaussian.out"
  ]
}
```

The host downloads only declared basenames into the local attempt's
`outputs/remote/` directory and verifies hashes.

## Parse

Parse one locally collected artifact selected by its workspace-relative ref:

<!-- ts_subagent_compute-example:parse -->
```json
{
  "operation": "parse",
  "backend": "gaussian",
  "nodeId": "n003",
  "intentId": "calc_n003_gaussian_opt_freq_0001",
  "artifactRef": "nodes/n003/attempts/calc_n003_gaussian_opt_freq_0001/outputs/remote/gaussian.out"
}
```

Parsed results may state termination, convergence, energies, frequencies,
coordinates, trajectory points, and artifact completeness. They must not state
Claim support, Gate verdicts, connectivity acceptance, conformer selection, or
study completion.

## Cancel

Cancel only a prepared remote intent whose authoritative receipt binds a job
ID:

<!-- ts_subagent_compute-example:cancel -->
```json
{
  "operation": "cancel",
  "backend": "gaussian",
  "nodeId": "n003",
  "intentId": "calc_n003_gaussian_opt_freq_0001"
}
```

Never repeat an ambiguous cancellation.

## Retry And Recalculation

A transfer failure before the submission request may return
`retry_disposition=retry_same_submission`. Only then repeat the exact submit
call for the same intent. Do not create a replacement intent for that recovery,
and never replay `submission_ambiguous`.

A scientifically changed calculation is a new immutable recalculation. Bind
its source and state exactly what changed:

<!-- ts_subagent_compute-example:recalculation-prepare -->
```json
{
  "operation": "prepare",
  "backend": "xtb",
  "nodeId": "n004",
  "purpose": "Refine the source xTB stationary point with tighter optimization and numerical accuracy.",
  "taskType": "opt_freq",
  "attemptKind": "recalculation",
  "recalculationRef": {
    "sourceNode": "n003",
    "sourceIntentId": "calc_n003_xtb_opt_freq_0001",
    "changedSettings": [
      "opt_level",
      "accuracy"
    ],
    "purpose": "refinement"
  },
  "inputArtifacts": [
    {
      "inputRole": "xyz",
      "artifactId": "art_fedcba987654321001234567"
    }
  ],
  "settings": {
    "method": "gfn2",
    "charge": "0",
    "uhf": "0",
    "opt_level": "vtight",
    "accuracy": "0.2"
  },
  "executionTarget": {
    "kind": "local"
  },
  "dryRun": false
}
```

Use `pending_controls` for a guard without a final result and
`unresolved_controls` for a completed control attempt that still needs safe
retry or reconciliation.
