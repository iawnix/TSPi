# Backend Contract

Backends are deterministic adapters. They express supported program tasks,
validate parameters, prepare immutable inputs/scripts, declare expected artifacts,
and parse local outputs. They do not choose a method, submit an unbound job,
update a Claim, or decide acceptance.

Use `ts_state mode=capabilities capabilityKind=compute` for the current machine-
readable catalog and [compute_tools.md](compute_tools.md) for public calls.

## Supported Tasks

- Gaussian: `sp`, `opt`, `freq`, `opt_freq`, `irc`.
- xTB: `sp`, `opt`, `freq`, `opt_freq`, `scan`, `md`.
- CREST: `conformer_search`.
- ASE: `neb`.
- QBICS: `dmecp`.

The catalog is an expression contract, not a recommendation or health check.

## Adapter Output

Preparation must declare exact generated files, commands, expected artifacts,
software profile, and parser contract without accepting arbitrary shell. Parse
must report structured program facts and provenance while retaining missing,
ambiguous, and failure states.

The host freezes every launch in `ts-calculation-intent/7`, including Node and
scientific-intent digests plus same-Node Attempt lineage. Any changed method,
input, command-relevant parameter, or expected output needs a new recalculation
intent. Older intent schemas are unsupported and are not converted.

The current execution boundary is explicit: local targets support deterministic
preparation and parsing only when `dry_run=true`; scheduler lifecycle actions
use a configured remote target. A backend adapter must not imply that a local
executable or remote profile is installed merely because its descriptor exists.

## Scientific Boundary

Parser facts are candidates for semantic Observations, not canonical science by
themselves. The Root verifies the primary artifact, chooses separate
`concept_id` records, and applies a Decision. Backends never infer mechanism,
endpoint identity, mode meaning, Claim status, ProofSpec verdict, or acceptance.
