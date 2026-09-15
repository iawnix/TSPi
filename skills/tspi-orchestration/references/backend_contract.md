# Backend Contract

Backends are deterministic adapters. They express supported program tasks,
validate parameters, prepare immutable inputs/scripts, declare expected artifacts,
and parse local outputs. Root selects the method and interprets verified results.

Use `ts_state mode=capabilities capabilityKind=compute` for the current machine-
readable catalog and [compute_tools.md](compute_tools.md) for public calls.

## Supported Tasks

- Gaussian: `sp`, `opt`, `freq`, `opt_freq`, `irc`.
- xTB: `sp`, `opt`, `freq`, `opt_freq`, `scan`, `md`.
- CREST: `conformer_search`.

ASE NEB and QBICS DMECP are not registered capabilities. A backend is not
public until it has a deterministic parser contract and task-validation tests;
an input preparer alone is insufficient.

Use the catalog to construct requests and `ts_remote doctor` to check readiness.

## Adapter Output

Preparation must declare exact generated files, commands, expected artifacts,
software profile, and parser contract without accepting arbitrary shell. Parse
must report structured program facts and provenance while retaining missing,
ambiguous, and failure states.

Parser output is factual and backend-owned; it does not decide whether the
requested task succeeded. The compute layer records program termination in
`program_status` and evaluates capability-specific completion separately in
`task_validation`. Neither field is a scientific verdict, and Gaussian
single-point, optimization, and frequency tasks never inherit transition-state
acceptance rules merely because they use the Gaussian parser.

The host freezes every launch in `ts-calculation-intent/7`, including Node and
scientific-intent digests plus same-Node Attempt lineage. Any changed method,
input, command-relevant parameter, or expected output needs a new recalculation
intent.

The current execution boundary is explicit: local targets support deterministic
preparation and parsing only when `dry_run=true`; scheduler lifecycle actions
use a configured remote target. Check the selected software profile before launching.

## Record Scientific Results

The Root verifies parser candidates against primary artifacts, chooses separate
`concept_id` records, and applies a Decision. Evaluate mechanism, endpoint identity,
mode assignment, and Claim acceptance with the relevant method Skill and ProofSpecs.
