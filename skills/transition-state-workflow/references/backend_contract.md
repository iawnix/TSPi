# Backend Contract

Backends are deterministic adapters. They express supported program tasks,
validate settings, prepare immutable inputs/scripts, declare expected artifacts,
and parse local outputs. They do not choose a method, submit an unbound job,
update a Claim, or decide acceptance.

Use `ts_workspace_context mode=compute_capabilities` for the current machine-
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

The host freezes those values in `ts-calculation-intent/4`. Any changed method,
input, command-relevant setting, or expected output needs a new intent.

## Scientific Boundary

Parser facts are candidates for semantic Observations, not canonical science by
themselves. The Root verifies the primary artifact, chooses separate
`concept_id` records, and applies a Decision. Backends never infer mechanism,
endpoint identity, mode meaning, Claim status, GateSpec verdict, or acceptance.
