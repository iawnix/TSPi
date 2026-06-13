# Connectivity Validation

Use this after Gaussian TS/Freq validation or when judging IRC/imaginary-mode endpoints. This layer checks whether the TS connects the intended reactant and product.

## Inputs

- Forward and reverse IRC endpoints, or optimized endpoint structures from imaginary-mode displacements.
- Optimized reactant and product references with the same atom order. If the
  references are constrained or lower-level endpoint hypotheses, report that
  limitation and do not call the TS fully connected to validated minima.
- Explicit reaction-center bonds and angles.

Supported inputs are `.xyz` and Gaussian `.out`/`.log`; Gaussian structures use the final orientation block.

`scripts/ts_imaginary_mode_follow.py compare` and `irc-compare` provide quick
covalent-radius connectivity screens from endpoint or IRC logs. Use those
summaries as evidence to decide what to validate next, not as a substitute for
the explicit reactant/product RMSD plus reaction-center bond/angle gates below.

## Run

```bash
python scripts/rmsd_connectivity_check.py \
  --forward irc_forward.out \
  --reverse irc_reverse.out \
  --reactant reactant_opt.xyz \
  --product product_opt.xyz \
  --bonds 2-5 7-5 8-5 6-7 6-8 \
  --angles 7-5-8 2-5-8 \
  --rmsd-threshold 0.75 \
  --bond-threshold 0.15 \
  --angle-threshold 8.0 \
  -o connectivity_check
```

The sign of Gaussian IRC is arbitrary. Unless the sign convention matters, allow either assignment:

- forward = product and reverse = reactant;
- forward = reactant and reverse = product.

## Fragment-Aware Cases

For dissociation, bimolecular products, or multiple conformers, global RMSD may be a pose metric rather than a chemical-connectivity metric. Prefer:

- bond graph and reaction-center metrics;
- fragment-wise alignment;
- chemically equivalent atom mappings;
- reference ensembles for multiple valid product poses.

For user-supplied two-molecule endpoints, first decide whether the claimed
reactant/product distinction is chemical or only a relative-pose difference. If
endpoint optimization changes only pose while preserving the same covalent and
reaction-center identity, classify the endpoint pair as `ambiguous_pose` or
`not_distinct_endpoints` rather than forcing a NEB/IRC connectivity decision.

If reaction-center metrics pass but only global pose fails, report `fragment_connected` or `ambiguous_pose`, not `not_connected`.

For unimolecular products with multiple valid conformers, use the explicit
conformer-aware mode only as a conservative diagnostic:

```bash
python scripts/rmsd_connectivity_check.py \
  --forward imaginary_plus_opt.xyz \
  --reverse imaginary_minus_opt.xyz \
  --reactant reactant_opt.xyz \
  --product product_conformer_ensemble_member.xyz \
  --bonds 1-5 3-5 \
  --conformer-aware \
  -o connectivity_check
```

`--conformer-aware` compares atom-mapped covalent bond graphs in addition to
RMSD and key internal coordinates. If the covalent graph matches an assignment
but RMSD, broken-bond nonbond distances, or conformational angles fail, the
tool reports `decision=conformer_identity_supported` with
`connectivity_supported=false` and suggests `claim_status=ambiguous,
outcome=wrong_endpoint, outcome_code=conformer_identity_only`. This is evidence
to build a product conformer ensemble or rerun endpoint checks, not evidence
for `accepted_ts`.

## Decision

Report `connected` only when one assignment passes all gates:

- endpoint/reference RMSD within threshold or fragment-aware equivalent;
- all requested key bonds within threshold;
- all requested key angles within threshold;
- the two endpoints represent different sides.

If only RMSD is available, call it a weak structural screen and request reaction-center metrics.

## Reframed Mechanisms

If a TS/Freq node was rejected because the mode or endpoint assignment was wrong
for the original reaction, do not relabel that old node. Create a new
connectivity-validation node for the reframed intended reaction, usually with:

- the old TS/Freq node as an `input_ref`;
- new reactant/intermediate/product references for the proposed step;
- explicit reaction-center bonds and angles for that step;
- a new connectivity evidence record attached to the new node.

The old TS/Freq output may satisfy the TS/Freq evidence gate only when it is
recorded as evidence for the new node. The accepted claim still belongs to the
new node and still requires connectivity to the reframed intended sides.

## Reporting

Include:

- forward/reverse endpoint paths;
- reactant/product reference paths;
- thresholds;
- selected assignment;
- RMSD and key bond/angle deviations;
- final `claim_status`, `outcome`, and `outcome_code` using the current state
  model. Valid successful pairs are `claim_status=endpoint_connected,
  outcome=connectivity_validated` for displacement/endpoint checks and
  `claim_status=irc_connected, outcome=connectivity_validated` for IRC checks.
  Failed connectivity should use `claim_status=rejected` or
  `claim_status=ambiguous` with `outcome=wrong_endpoint` and a diagnostic
  `outcome_code` such as `irc_not_connected`, `endpoint_assignment_failed`,
  `not_distinct_endpoints`, or `ambiguous_pose`.
