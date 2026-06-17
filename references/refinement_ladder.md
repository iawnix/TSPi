# Low-To-High Refinement Ladder

Use this reference when a low-level scan, NEB, dimer, QST, manual guess,
Gaussian-External-xTB run, or reaction-network search has produced a candidate
geometry that may become a higher-level TS. For method evidence limits, read
`references/mechanism_analysis_sources.md`; for choosing the search strategy and
level/backend, read `references/backend_selection.md`.

Low-level results are allowed to guide the search. They do not validate the
final TS claim. The workflow must explicitly transfer, refine, and validate the
candidate on the intended surface before reporting anything beyond candidate
evidence.

## Standard Ladder

```text
low-level endpoint/path/candidate
  -> candidate quality check
  -> geometry transfer to target level
  -> high-level TS optimization
  -> high-level frequency and mode check
  -> connectivity validation
  -> accepted_ts
```

Each arrow is a separate decision point. If a step fails, record what changed
and backtrack to the closest chemically meaningful branch.

## Candidate Quality Check

Before launching high-level refinement, verify and record:

- atom count, atom order, and mapping are unchanged;
- charge and multiplicity match the mechanism hypothesis;
- forming and breaking bonds sit between the intended endpoint values or have a
  chemically justified near-TS geometry;
- the candidate is not the first or last NEB image;
- the mode/path motion is not merely a conformer, rotation, translation,
  fragment drift, or constrained artifact;
- fragment identities are preserved for multicomponent systems;
- the low-level method did not change proton location, bond identity, spin
  state, charge localization, or reaction-center chemistry in a way that
  contradicts the target mechanism.

If these checks fail, close or mark the branch `ambiguous`/`rejected` with
reflection instead of starting high-level refinement.

## Geometry Transfer

Transfer only the geometry and the documented chemical hypothesis. Do not
transfer low-level energies, barriers, convergence status, or method-specific
electronic interpretation as high-level evidence.

For the first target-level job:

- preserve atom ordering and charge/multiplicity;
- use a route appropriate for TS refinement, not endpoint minimization;
- keep node-scoped input, output, checkpoint, and scratch paths;
- cite the low-level candidate as the parent evidence;
- record changed variables such as method, basis, solvent, dispersion,
  constraints removed, and symmetry handling.

## High-Level Refinement

High-level refinement usually means Gaussian/DFT TS optimization seeded from the
candidate. It may use `Opt=(TS,CalcFC,NoEigen)` or another explicit TS route
when the candidate is already chemically plausible. The route is not a default
search method; it is the refinement test for a specific candidate.

During refinement, monitor whether the structure keeps the intended reaction
center. If it drifts:

- save the drifted geometry and output;
- record which bonds, angles, fragments, charge/spin features, or endpoint
  assignments changed;
- backtrack to candidate generation, endpoint definition, level/backend choice,
  or pathway decomposition.

Do not keep restarting a refinement that repeatedly walks to the same wrong
minimum or wrong saddle without changing a chemical variable.

## Validation Gates

Set `claim_status=tsfreq_validated` only after the target-level TS/Freq output
passes the Gaussian validation gates:

- normal termination;
- stationary point evidence;
- optimization convergence evidence;
- exactly one imaginary frequency;
- mode motion matches the intended reaction center.

Set `claim_status=accepted_ts` only after `tsfreq_validated` plus endpoint or
IRC connectivity validation proves the intended elementary step.

## Failure Classification

Do not summarize refinement failure as "did not work". Classify the failure:

- low-level candidate was not TS-like;
- high-level surface changed the reaction-center identity;
- no imaginary frequency;
- multiple imaginary frequencies;
- only imaginary mode is not the intended reaction coordinate;
- candidate converged to endpoint or conformational saddle;
- endpoint references were wrong or incomplete;
- atom mapping, charge, multiplicity, solvent, or electronic state was wrong;
- numerical failure occurred before scientific evidence was available.

Use that classification to choose the next branch.
