# Program Runtime Failures

This reference helps an agent diagnose and respond to calculation/runtime
failures without changing the workspace state model. It is a troubleshooting
guide, not a schema extension and not an automatic retry policy.

Read it when a calculation did not produce usable evidence because the program,
scheduler, parser, environment, or remote lifecycle failed. For Gaussian
TS/Freq evidence, read this together with `references/gaussian_validation.md`.

## Boundary

Keep these concerns separate:

- Program failure: the calculation did not complete a usable protocol step
  because the executable, scheduler, input syntax, SCF, optimizer, IRC, parser,
  scratch, memory, or artifact fetch failed. Close a candidate or validation
  node with `closure.program.outcome=failure`; do not add a hypothesis or audit
  status.
- Chemistry failure: the calculation completed and the evidence refutes the
  declared prediction. Close the validation node with
  `closure.program.outcome=success`, register the negative evidence, then use a
  `mechanism/evaluate` node to set `hypothesis.status=unsupported|ambiguous`.
- Strategy choice: retrying, changing a route keyword, replacing a candidate,
  changing a hypothesis, or stopping remains an agent decision. Do not encode it
  as a validator rule.

## Triage Order

Before choosing a retry or branch, inspect artifacts in this order:

1. Remote lifecycle: `remote_status.json`, `remote_receipt.json`, PID/process
   status, launcher stderr/stdout, and whether the remote directory exists.
2. Program driver output: `g16_driver.out`, `g16_driver.err`, scheduler logs,
   shell exit status, environment setup warnings, and scratch path creation.
3. Primary program output: Gaussian `.out`/`.log`, xTB output, ASE/QBICS logs,
   and whether the expected output was produced under the current node.
4. Input and route intent: `.gjf`, charge, multiplicity, method/basis, Gen/ECP
   sections, checkpoint dependencies, `%oldchk`, `%chk`, memory, nproc, and
   route keywords.
5. Parser diagnostics: selected Link1/job section, route readback,
   convergence rows, normal/error termination, frequency table selection, and
   missing artifacts.
6. Chemistry context: whether the seed, constrained scan, QST interpolation, or
   TS guess is chemically plausible before spending more runtime on the same
   route.

Record the failure summary as node-owned evidence or closure program facts. If
the next node depends on it, cite that evidence as `previous_attempt_summary`.

## Common Runtime Classes

- Environment/bootstrap failure: executable not found, profile sourcing failed,
  license failure, missing library, wrong interpreter, or conda/env mismatch.
  Fix the environment before making chemistry conclusions.
- Remote lifecycle failure: duplicate live PID, missing remote directory,
  scheduler rejection, killed job, missing fetched artifacts, or stale scratch.
  Treat this as administrative/program failure.
- Input assembly failure: malformed route, missing blank lines, bad charge or
  multiplicity, missing Gen/ECP block, wrong checkpoint name, unsupported
  keyword combination, or path escape. Repair the input and rerun only after the
  intended route is clear.
- SCF failure: energy/gradient for a step was not completed. Handle this as an
  electronic-structure convergence problem before diagnosing geometry
  optimization failure.
- Optimization failure: the optimizer reached a step limit, oscillated, lacked
  a stationary point, or repeatedly failed convergence rows.
- IRC failure: corrector/convergence failure, MaxPoints/StepSize issues, or
  early termination before endpoints are assignable.
- Parser failure: the output may be valid but the parser selected the wrong
  section, mixed Link1 sections, missed convergence evidence, or lacks the
  expected artifact. Fix the parser use/section selection before changing the
  chemistry route.

## Gaussian Optimization And TS Optimization

Sobereva's Gaussian optimization-convergence note is useful as a heuristic
source for Gaussian geometry optimization and TS optimization failures. The
agent should adapt it conservatively:

- Diagnose the trend before rerunning. Inspect the optimization trajectory,
  energy, force, and displacement history. If the values still trend down, a
  continuation may be justified; if they oscillate, simply raising `MaxCycle` is
  usually wasted runtime.
- If the failed job has a useful intermediate structure, restart from the lowest
  energy or lowest force frame rather than blindly restarting from the original
  geometry.
- For DFT grid-related noise, especially older Gaussian defaults or
  Minnesota-type functionals, try a finer integration grid such as
  `Int=UltraFine` when it is not already the default.
- If an SMD optimization behaves poorly and solvent is not essential for the
  geometry step, consider IEFPCM or gas-phase optimization followed by the
  intended solvent single-point, with the modeling assumption recorded.
- Improve the Hessian when feasible. For TS optimization, `Opt=CalcFC`,
  `Opt=CalcAll`, or in Gaussian 16 `Opt=RecalcFC=N` can be more important than
  for minima because TS searches are more Hessian-sensitive.
- Try a different optimizer only as a route-level experiment, for example RFO,
  GDIIS, or GEDIIS, and record the changed route explicitly.
- Change coordinates when the failure is coordinate-related. Cartesian
  coordinates may help clusters or redundant-coordinate breakdowns;
  ModRedundant coordinates may help weak contacts, hydrogen bonds, or reaction
  coordinates that Gaussian did not include usefully.
- Reduce the trust radius for oscillatory steps, for example by combining
  smaller `MaxStep` with `NoTrust` when the trajectory repeatedly overshoots.
- Treat symmetry deliberately. Break artificial high symmetry when it traps the
  optimization; enforce real symmetry only when the structure is genuinely
  converging toward that point group.
- Relaxing convergence (`Opt=Loose`) is only a last resort for low-precision
  preparatory geometries. Do not use it to validate a TS/Freq or accepted TS
  claim.
- Changing method/basis can be used to generate a better starting geometry, but
  it changes the potential-energy surface. Keep the final validation at the
  intended level of theory unless the research method is explicitly changed.
- For TS searches, failure often reflects a poor TS guess rather than a generic
  optimizer problem. QST2 interpolation can produce an unphysical guess; if the
  trajectory moves into a wrong motif, switch to a chemically guided TS guess or
  another candidate-generation strategy instead of only tuning optimizer knobs.

These are heuristics, not guarantees. If several route variants fail with the
same shape, read `references/strategy_reflection.md` before spending more
runtime on similar seeds.

## Decision Guidance

- Same Node objective and scientific protocol, only a technical recovery
  changed: use `ts-calculation-intent/3 attempt_kind=retry` under that Node.
- A method, basis, model, coordinate strategy, or scientific question change
  is a Root decision. Record it as a recalculation operation or open a new child
  Node with an explicit objective and Claim refs.
- A replacement candidate or alternative explanation should remain visible as
  a new operation, Node, or Claim rather than being hidden inside a retry.
- Environment, parser, artifact-fetch, or remote lifecycle repair:
  use administrative/provenance evidence where appropriate and avoid chemistry
  verdicts.

## Minimal Failure Summary

A useful `previous_attempt_summary` should include:

- Node ID, objective/tags, calculation intent, program, host, input path,
  output path, and exit state;
- the first hard failure signal, not only the last line of stderr;
- route intent versus route readback when Gaussian output exists;
- whether any geometry, checkpoint, Hessian, or frequency artifact is reusable;
- what changed in the proposed next attempt;
- why the next act is a technical retry, recalculation, solution branch,
  hypothesis branch, or stop decision.

## Source Note

The Gaussian optimization heuristics above summarize the practical categories in
Sobereva, "Common methods to facilitate geometry optimization convergence in
quantum chemistry calculations" (`http://sobereva.com/164`). The source focuses
on optimization convergence; use other references or direct log evidence for
SCF, license, scheduler, memory, and syntax-specific failures.
