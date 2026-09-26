# Backend Contract

Backends are deterministic adapters. They express supported program tasks,
validate parameters, prepare immutable inputs/scripts, declare expected artifacts,
and parse local outputs. Root selects the method and interprets verified results.

Use `research.read mode=capabilities capabilityKind=compute` for the current machine-
readable catalog and
[compute_tools.md](../../tspi-orchestration/references/compute_tools.md) for
public calls.

## Supported Tasks

- Gaussian: `sp`, `opt`, `ts`, `freq`, `opt_freq`, `irc`, and the registered
  relaxed-scan capability `gaussian.scan@1`.
- xTB: `sp`, `opt`, `freq`, `opt_freq`, `scan`, `md`.
- CREST: `conformer_search`.
- ASE NEB: the registered `ase.neb@1` capability, using the xTB CLI calculator
  by default or the explicit `calculator=gaussian_cli` mode when Gaussian
  per-image forces are required.

QBICS DMECP is not a registered capability. A backend is not public until it
has a deterministic parser contract and task-validation tests; an input
preparer alone is insufficient.

Use the catalog to construct `compute.run` requests. Select
`executionTarget.kind = "local"` or `"remote"` and, when a shared
`compute.toml` is installed, the corresponding environment name; the lifecycle
and result contract are the same. Remote readiness is checked during calculation
preflight; it is not a separate calculation API.

For example, a local request can bind `{"kind":"local","environment":"local"}`;
the same capability can bind `{"kind":"remote","environment":"cluster_1w",...}`.

## Adapter Output

Preparation must declare exact generated files, commands, expected artifacts,
Backend binding, Compute environment, and parser contract without accepting arbitrary shell. Parse
must report structured program facts and provenance while retaining missing,
ambiguous, and failure states.

Parser output is factual and backend-owned; it does not decide whether the
requested task succeeded. The compute layer records program termination in
`program_status` and evaluates capability-specific completion separately in
`task_validation`. Neither field is a scientific verdict, and Gaussian
single-point, optimization, transition-state optimization, and frequency tasks
never inherit scientific transition-state assessment rules merely because they
use the Gaussian parser.

The host freezes every launch in `ts-calculation-intent/7`, including Node and
scientific-intent digests plus same-Node Attempt lineage. Any changed method,
input, command-relevant parameter, or expected output needs a new recalculation
intent.

The execution boundary is explicit but not remote-only: local targets support
deterministic preparation when `dry_run=true` and start a bounded, durable
Attempt-local worker when `dry_run=false`. Remote targets use the configured
remote environment only when `dry_run=false`; remote dry-runs generate and
validate a submission plan without contacting the scheduler. Check the selected
environment and Backend binding before launching.

## Record Scientific Results

The Root verifies parser output against primary artifacts, chooses separate
Finding statements, and applies `research.change`. Evaluate mechanism, endpoint
identity, mode assignment, and Claim status with the relevant method Skill and
Gate criteria when a visible verdict is useful.
