# Program Runtime Failures

Use this reference when a calculation, parser, environment, scheduler, transfer,
or remote lifecycle did not produce usable scientific facts. It is a
troubleshooting guide, not a workflow, schema extension, or automatic retry
policy.

## Contents

- [Keep Failure Domains Separate](#keep-failure-domains-separate)
- [Triage Order](#triage-order)
- [Common Classes](#common-classes)
- [Retry, Recalculation, Or New Node](#retry-recalculation-or-new-node)
- [Durable Failure Summary](#durable-failure-summary)
- [Source Note](#source-note)

## Keep Failure Domains Separate

- **Control or environment failure**: preparation, upload, scheduler request,
  activation, scratch setup, collection, or parsing did not complete its typed
  operation. Preserve operational records and do not update a Claim from the
  failure alone.
- **Program failure**: the scientific program started but did not complete the
  requested protocol. Preserve its output and diagnostics. A failed optimizer
  or IRC is normally not negative scientific Evidence about the target Claim.
- **Scientific contradiction**: the requested protocol completed, local
  artifacts were verified, and their facts contradict the target Claim or fail
  a declared Gate. Register those negative facts and make an explicit Claim
  update through `end_node`.
- **Strategy choice**: retrying, changing settings or method, replacing a
  candidate, revising a Claim, asking the user, or stopping remains a Root Agent
  decision.

Scheduler state, operator outcome, and program termination are operational facts
until a deterministic parser and normal Decision register scientifically useful
facts from local artifacts.

## Triage Order

Inspect the current attempt under
`nodes/<node>/attempts/<intent>/` in this order:

1. `intent.json` and `prepared.json`: confirm the bound backend, task, inputs,
   digests, expected artifacts, execution target, and resources.
2. `submit_guard.json`, `submit_result.json`, `remote_receipt.json`, and any
   reconciliation: determine whether a scheduler effect was attempted, known,
   retryable, or ambiguous.
3. `status.json` and remote `program_status.json`: keep program phase, exit
   status, and Torque state separate.
4. Collected files under `outputs/remote/`: inspect scheduler streams, driver
   output, and the primary program output that actually exist.
5. Input and route intent: check charge, multiplicity, method, basis, blank-line
   structure, control sections, checkpoints, memory/process settings, and task
   keywords.
6. Parser output under `outputs/parsed/`: check selected job section, route
   readback, convergence rows, termination, frequency table, expected companion
   files, and source digests.
7. Scientific context: decide whether the candidate and requested protocol were
   meaningful before spending more runtime on a similar attempt.

Do not guess a Gaussian syntax error from a missing output, or infer that no job
existed from a lost outer tool response. Reconcile durable control records first.

## Common Classes

### Pre-effect request or staging failure

Examples include invalid request fields, unresolved artifact IDs, missing local
inputs, directory creation failure, upload failure, or digest mismatch before
the remote submission script starts. The typed result must state whether the
same exact submission binding may be retried. Repeat submit only for
`retry_disposition=retry_same_submission`.

### Ambiguous external effect

If submit or cancel started but no authoritative remote record can be read, the
effect is unknown. Do not retry. Inspect later status, remote submission records,
receipts, declared outputs, or ask the remote operator to reconcile the bound
submission ID.

### Remote bootstrap failure

`program_status.json.phase=scratch_setup` means the configured scratch policy
failed. `phase=activation` means the installation-owned software profile did not
initialize. Neither is a chemistry result. Repair installation configuration or
the execution host before changing a scientific route.

### Input assembly or syntax failure

Examples include malformed Gaussian route/title/charge sections, unsupported
keywords, invalid xTB control input, missing Gen/ECP data, or an unavailable
checkpoint. Correct the input through the adapter contract and create the
appropriate new immutable calculation intent. Do not edit a prepared attempt.

For Gaussian, use canonical program keywords such as `M062X`, not display forms
such as `M06-2X`, and parse the complete route before submission when the typed
adapter has enough information to do so.

### SCF or electronic-structure failure

An incomplete SCF means the energy or gradient for the step was not obtained.
Diagnose electronic convergence, state, charge/spin, method, and numerical
settings before describing the geometry optimizer as the root cause.

### Optimization failure

Inspect the trajectory, energy, force, and displacement trends. A continuation
may be justified when the structure is steadily approaching a stationary point;
oscillation or a wrong motif usually needs a changed strategy rather than only a
higher step limit.

Useful Gaussian considerations include:

- use an adequate integration grid for functionals sensitive to grid noise;
- improve the Hessian with `CalcFC`, `CalcAll`, or an appropriate `RecalcFC`;
- change coordinate representation only when diagnostics support a coordinate
  problem;
- adjust trust radius or optimizer only as an explicit changed setting;
- break artificial symmetry or preserve real symmetry deliberately;
- restart from a useful verified frame rather than an arbitrary last geometry;
- use a lower-level method only as candidate generation unless the research
  method itself is explicitly changed.

`Opt=Loose` is not acceptable final TS/Freq validation. Gaussian accepting a
structure on negligible forces does not satisfy a stricter all-convergence-row
policy; refine and re-evaluate the registered facts when required.

### IRC failure or finite endpoint

Separate program failure from a finite but valid endpoint. A corrector failure,
early termination, or unassignable direction does not pass connectivity. A path
that reaches `MaxPoints` with normal program behavior may still provide a finite
encounter endpoint; disclose the finite-distance limitation and use independent
endpoint facts where scientifically justified.

Gaussian IRC point 0 may be a coordinate-free TS marker. Parsers must begin the
coordinate series at the first point containing a structure rather than treating
missing point-0 coordinates as a path failure.

### Parser failure

The program output may be valid while the parser selected the wrong Link1/job
section, mixed frequency tables, failed route normalization, or required an
undeclared companion file. Repair parser selection or implementation before
changing chemistry. Route `MaxCycle` and Gaussian internal effective step limits
are different diagnostics and must not be required to show the same number.

## Retry, Recalculation, Or New Node

- Repeat submit for the same intent only when the control result explicitly
  permits the same submission binding.
- Use a new `attempt_kind=retry` calculation when the scientific protocol is
  unchanged but a completed technical attempt must be rerun with the same
  settings and declared inputs.
- Use `attempt_kind=recalculation` with `recalculation_ref` when settings,
  method, coordinate strategy, or refinement purpose changed. List every
  changed setting.
- Open a new Node when the bounded research objective or scientific question
  changes, or when keeping an alternative line visible improves the research
  graph.
- Revise or add a Claim only when the scientific statement changes.
- Stop explicitly when further work is unjustified or requires user input.

The Kernel does not choose among these options.

## Durable Failure Summary

Keep the useful facts in the calculation records and the Node's terminal
summary/open questions. A concise recovery summary should identify:

- Node, intent, backend/task, execution target, and program;
- the first hard failure signal and its source artifact;
- whether a remote effect was attempted and whether a job ID is known;
- intended route/settings versus program readback when available;
- reusable geometry, checkpoint, Hessian, trajectory, or parsed facts;
- whether the next action preserves or changes the scientific protocol;
- remaining ambiguity and the exact record needed for reconciliation.

Do not invent another compatibility field or register an operational failure as
scientific Evidence merely to make it visible. Use the existing Node result,
operation link, attempt records, and normal provenance.

## Source Note

The Gaussian optimization heuristics summarize practical categories discussed
by Sobereva, "Common methods to facilitate geometry optimization convergence in
quantum chemistry calculations" (`http://sobereva.com/164`). That source does
not establish scheduler, license, memory, parser, or chemistry-specific causes;
verify those from the current artifacts.
