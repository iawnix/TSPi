# Strategy Reflection

This file is a heuristic library, not a workflow. Hard constraints live in the
workspace contract, declared Claim requirements, deterministic Gates, and audit
policies. Nothing here changes a validator or selects a next Node automatically.

Read it when relevant Node results, calculation attempts, or Evidence show one
of these patterns:

- two or more IRC attempts linked to the same target Claim assign both
  directions to the same side;
- repeated Gaussian attempts show the same route mismatch or ineffective
  optimization behavior;
- the target Claim describes excited-state, open-shell, or non-adiabatic
  chemistry;
- repeated results indicate a wrong basin, incompatible endpoints, or an
  ambiguous electronic surface.

The Root Agent must inspect the cited records and decide whether any heuristic
applies. Project-specific priors belong in the research workspace or its source
material, not in this package reference.

## Contents

- [Endpoints Do Not Select A TS Search Method](#endpoints-do-not-select-a-ts-search-method)
- [Repeated Same-Shape Gaussian Failure](#repeated-same-shape-gaussian-failure)
- [Repeated Same-Side IRC](#repeated-same-side-irc)
- [Excited-State, Open-Shell, And Non-Adiabatic Claims](#excited-state-open-shell-and-non-adiabatic-claims)
- [Constraint-Derived Loose Fragments](#constraint-derived-loose-fragments)
- [Multiple Plausible Sites Or Conformers](#multiple-plausible-sites-or-conformers)
- [Recording The Decision](#recording-the-decision)

## Endpoints Do Not Select A TS Search Method

Reactant and product endpoints define target basins for validation. They do not
by themselves justify QST2/QST3 or any other candidate method. Ask whether atom
mapping is reliable, conformers are compatible, stoichiometry matches, and the
Claim describes one elementary step. If not, a scan, NEB, chemically guided
seed, or revised Claim may be more appropriate.

This heuristic does not reject QST when both endpoints are optimized under
matching conditions, mapping is unambiguous, and interpolation is chemically
meaningful.

## Repeated Same-Shape Gaussian Failure

When several attempts fail with the same route readback, step-limit, corrector,
or convergence pattern, inspect the route and optimizer behavior before
perturbing another similar seed. Confirm that Gaussian accepted the intended
keywords and distinguish requested `MaxCycle` from Gaussian's internal step
diagnostics.

This heuristic does not apply when failures have different causes, such as one
scratch failure and one chemically poor initial geometry.

## Repeated Same-Side IRC

Two completed IRC attempts that collapse to the same basin on both directions
can indicate a shoulder, a soft intrabasin mode, or a saddle for another
coordinate. Compare the imaginary displacement with the declared reaction
center and consider whether a different candidate-generation strategy tests the
Claim more directly.

This heuristic does not apply when one path terminated before a direction was
assignable. Finish or diagnose the incomplete calculation before interpreting
the pattern.

## Excited-State, Open-Shell, And Non-Adiabatic Claims

Do not reduce a surface-changing mechanism to one unusual ground-state IRC.
State the surface or spin character of each relevant basin and the location of
any crossing. Use state-character, electronic-structure, or crossing evidence
as required by the Claim.

This heuristic does not require a crossing model when diagnostics support one
consistent adiabatic state across the complete elementary step.

## Constraint-Derived Loose Fragments

Hand-interpolated or strongly constrained loose fragments are candidate
geometries. Before treating one as a TS/Freq seed, test whether the structure
remains near the candidate after releasing the constraint or after a short scan
through the coordinate. Record the changed operation and resulting facts.

This heuristic does not apply when an earlier verified operation already
released the constraint and reproduced the same local structure.

## Multiple Plausible Sites Or Conformers

The Kernel permits sibling or child Nodes but does not require parallel work.
Use chemical plausibility, cost, symmetry, available Evidence, and the user's
goal to decide whether alternatives should run sequentially or together. Keep
each alternative visible through an explicit Claim, Node objective, or linked
operation.

Parallel work can be efficient for cheap symmetry-related stereochemical or
regiochemical alternatives. It is less useful when it splits scarce compute
across unrelated high-cost mechanisms without a discriminator.

## Recording The Decision

When a heuristic changes the plan:

1. cite the Node, Claim, Evidence, Gate, or calculation records that show the
   pattern;
2. state which scientific assumption or technical route is changing;
3. use `attempt_kind=retry` only for the same scientific protocol after a
   retry-safe technical failure;
4. use a recalculation or new Node for changed method, settings, coordinate
   strategy, candidate, or scientific question;
5. leave prior failures intact and close the current Node explicitly if its
   bounded objective is complete, inconclusive, blocked, or stopped.
