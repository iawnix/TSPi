# Compute Operator

`ts_subagent_compute` executes one typed action selected by the Root Agent. The
child cannot select a method, change a prepared intent, register Evidence, or
update a Claim.

## Prepare

Provide:

- Node ID and scientific purpose;
- backend and task type;
- `primary|retry|recalculation` attempt kind and any required source ref;
- logical `artifactId` plus `inputRole` bindings;
- task settings;
- local or configured remote target and complete resources;
- optional dry-run.

Preparation writes `ts-calculation-intent/3`, assigns the intent ID and attempt
directory, resolves artifact paths and hashes, generates inputs/scripts, and
binds expected artifacts. It rejects raw source paths, arbitrary command
arguments, transport endpoints, hostnames, and remote roots.

## Control Actions

- `submit`: run exact preflight, stage the immutable manifest, and issue one
  bound scheduler request.
- `inspect`: return bounded scheduler/program/remote-artifact facts.
- `collect`: fetch declared artifacts and verify them without requiring current
  scheduler visibility.
- `cancel`: issue one bound cancellation request.
- `parse`: parse collected local artifacts into deterministic program facts.

A structured tool return is not the same as action success. Preserve
`action_outcome=unknown` for ambiguous scheduler effects. Distinguish
pre-submit transfer failure, request started without a known result, known job
ID with later connection failure, and confirmed scheduler rejection.

## Scientific Boundary

Parsed results may state termination, convergence, energies, frequencies,
coordinates, trajectory points, and artifact completeness. They must not state
Claim support, Gate verdicts, connectivity acceptance, conformer selection, or
study completion. Register relevant parsed facts later as Evidence and invoke a
Gate explicitly.

Use `pending_controls` for a guard without a final result and
`unresolved_controls` for a completed control attempt that still needs safe
retry or reconciliation. Never duplicate an ambiguous submit or cancel.
