# Strategy Reflection

This file is a heuristics library, not a workflow. Hard constraints live in
`workspace_contract.md` and the evidence gates. Nothing in this file can
change `validate_workspace`, `accepted_audit`, or any verdict. Each entry
ends with a reflection question, not a directive; each entry lists at least
one case where the heuristic does not apply.

Read this file when any of the following holds:

- the same `hypothesis_ref` has ≥2 consecutive nodes whose IRC endpoint
  assignments fall on the same side (product/product or reactant/reactant);
- the same `hypothesis_ref` has ≥2 Gaussian route-mismatch diagnostics or
  route-ineffective closures;
- the active `initial_mechanism_hypothesis.structured_claim.electronic_model`
  marks `excited_state`, `open_shell`, or `non_adiabatic`;
- any recent `reason_code` matches `wrong_basin|route_ineffective|surface_ambiguous`.

Every example uses a generic label (e.g. "diazo → ketene via carbene
channel") rather than a specific molecule. Project-specific priors belong in
the project's own `.TODO.md` or task README, not here.

## R/P endpoints do not choose the TS-search method

Reactant and product endpoints define the target basins for validation. They
do not by themselves justify QST2/QST3 or any other method. Ask: is atom
mapping reliable? Are conformers compatible? Is the elementary step really a
single elementary step? Only if all three hold is QST a reasonable default;
otherwise a scan-based or manual-seed candidate is often better.

*Does not apply when:* the endpoints have been optimized under matching
conditions, atom mapping is unambiguous, and the mechanism claim is a single
elementary step with no proposed intermediate.

## Repeated same-shape Gaussian failure — address route, not seed

When several TS/Freq or IRC jobs fail the same way (route ineffective, step
limit reached even with `MaxCycle` bump, parser desync, corrector
convergence), the failure is likely a backend/route property, not a seed
quality property. Ask: does the log actually reflect the requested route?
Was the keyword accepted? Is there a Gaussian-internal step limit
overriding the requested one? Small seed perturbations under an ineffective
route waste the budget.

*Does not apply when:* the failures have distinct root causes (one on scratch
disk full, one on a genuinely bad initial guess) — treat each on its own.

## Repeated wrong-basin IRC — question the TS type, not just the seed

Two or more IRC runs collapsing to the same side (product/product or
reactant/reactant) under the same hypothesis suggests the imaginary mode is
a shoulder, a soft mode in the same basin, or a saddle for a different
reaction coordinate — not that the seed is slightly off. Ask: does the
imaginary mode's displacement vector actually align with the proposed
reaction center? Would a different TS type (e.g. constrained-scan seed
instead of QST) reach a different basin? Continuing to perturb structurally
similar candidates is unlikely to escape the basin.

*Does not apply when:* one of the two IRC runs terminated early with a
program failure that plausibly aborted before the true forward branch —
finish that run before drawing conclusions.

## Photochemistry / open-shell / non-adiabatic — decompose by surface first

Excited-state, open-shell, or non-adiabatic hypotheses are not a single
ground-state R→P search with an unusual TS. Before framing any IRC, ask:
what surface is the reactant on? What surface is the TS on? Where is the
crossing (if any)? A ground-state R→P IRC over a mechanism that involves a
surface crossing is a category error — the answer will not match the
hypothesis regardless of TS quality.

*Does not apply when:* the state character has been diagnosed and remains
constant across R, TS, and P — a same-surface reaction where excitation
only altered the starting basin can be treated with the same-surface
gates.

## Loose fragments placed by interpolation — candidate only, not TS/Freq seed

Structures produced by hand-interpolating or ad-hoc-constraining a small
loose fragment (N₂, CO, small ligand) are candidates. Before promoting to
TS/Freq, ask: does the constraint hide the true saddle geometry? A short
constraint-release relaxation or a small scan through the constrained
coordinate is cheap and tells you whether the region is stable without the
constraint. Skipping this step often produces TS/Freq attempts that either
fail to converge or converge to a constraint-artifact saddle.

*Does not apply when:* the constraint has already been released in a
previous node and the released geometry re-converged near the constrained
one within a small RMSD.

## Multiple plausible reaction sites — sequence, don't parallelize

When a hypothesis admits multiple a priori plausible reaction sites or
functional-group participants, attack the site with lower structural strain
and stronger literature precedent first. Ask: which alternative site has
the fewest a priori objections? Which has evidence I can reuse? Parallel
primary lines split compute and attention; the alternative is best kept as
a checked comparator branch that runs after the primary line is either
supported or refuted.

*Does not apply when:* the alternatives differ only in stereochemistry or
regiochemistry within a symmetric neighborhood — those are cheap to run
together and inform each other.
