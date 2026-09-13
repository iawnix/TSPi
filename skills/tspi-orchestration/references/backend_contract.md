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
- ASE: `neb`.
- QBICS: `dmecp`.

Use the catalog to construct requests and `ts_remote doctor` to check readiness.

## Adapter Output

Preparation must declare exact generated files, commands, expected artifacts,
software profile, and parser contract without accepting arbitrary shell. Parse
must report structured program facts and provenance while retaining missing,
ambiguous, and failure states.

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
