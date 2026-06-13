# Candidate Generation

Use this for xTB, ASE, NEB, scans, QST, dimer, and guessed structures before Gaussian validation.
For mechanism-analysis records from candidate-generation methods, read
`references/mechanism_analysis_sources.md`; xTB/ASE evidence is usually
screening or candidate-level evidence, not final electronic, orbital, or barrier
proof.

## Endpoint Rule

Treat user-supplied reactant and product structures as reference endpoint
hypotheses until proven otherwise. Optimize or stabilize endpoints before path
searches. For NEB especially, unoptimized or unstable endpoints can create
artificial paths, endpoint barriers, and wrong highest-energy images.

For two-molecule, multicomponent, ion-pair, encounter-complex, or flexible
systems, do not assume the supplied relative pose is a minimum. First check
fragment identity, reaction-center bonds/angles, and whether each side remains
distinct during optimization. Whole-system RMSD is secondary unless the intended
chemistry requires a specific bound complex pose.

Endpoint states:

- `validated_minimum`: optimized at the intended level and distinct.
- `lower_level_minimum`: optimized at xTB or another cheaper level, still
  awaiting intended-level confirmation.
- `constrained_reference`: optimized with light, chemically justified
  constraints to preserve endpoint identity.
- `reference_hypothesis`: supplied or drawn geometry, not yet a minimum.
- `collapsed_or_unstable`: optimization changes side, merges R/P, dissociates,
  or loses the intended reaction-center identity.

Do not run direct Gaussian-NEB from `reference_hypothesis` or
`collapsed_or_unstable` endpoints. Backtrack to endpoint discovery, constrained
preoptimization, conformer/pose search, relaxed scan, or intended-level endpoint
stability validation.

In the bundled ASE/NEB config, record the endpoint state explicitly:

```json
"endpoint_validation": {
  "reactant_state": "lower_level_minimum",
  "product_state": "lower_level_minimum",
  "level": "GFN2-xTB preoptimization",
  "evidence": "nodes/n005_endpoint_gate/parsed/endpoint_summary.json"
}
```

Allowed ready states for candidate promotion are `validated_minimum`,
`lower_level_minimum`, and `constrained_reference` on both sides. The default is
`reference_hypothesis`, which lets `prepare` record the branch but prevents
promotion to `candidate_found`.

Record:

- method and level;
- charge and multiplicity;
- final energy;
- minimum/frequency status if available;
- key reaction-center bonds/angles;
- fragment identity and relative-pose assumptions;
- constraints used to preserve endpoint identity;
- endpoint state from the list above.

## Level Selection: xTB vs Gaussian

Use xTB and Gaussian at different evidence layers. Do not treat them as
interchangeable optimizers.

| Task | Prefer xTB/GFN when | Prefer Gaussian/DFT when |
| --- | --- | --- |
| Initial cleanup | structures are rough, many poses/conformers must be screened, or the goal is to remove obvious clashes | atom order, charge, multiplicity, and composition are fixed and the endpoint will become validation evidence |
| Endpoint optimization | endpoints are hypotheses and a cheap stability check is needed first | endpoint minima will be used as QST/NEB/IRC references or final connectivity references |
| NEB/path search | broad path discovery, xTB-NEB, scan, or dimer is being used to produce candidates | lower-level paths are promising but electronically sensitive, or the branch needs Gaussian-force refinement before TS/Freq |
| Open-shell/HAT/PCET/charge transfer | only for screening geometries and reaction-center trends | use Gaussian earlier for spin, charge, state, barrier, and frequency-sensitive claims |
| Weak complexes/multicomponent poses | pose/conformer screening and constrained references | validating distinct bound/encounter minima or rejecting a pose-sensitive mechanism |
| Final TS evidence | never sufficient by itself | required for `tsfreq_validated` and any accepted TS path |

xTB is appropriate for speed and breadth: endpoint preoptimization, conformer or
relative-pose screening, constrained-reference discovery, relaxed scans, NEB,
dimer-like candidate generation, and branch recovery after failures. Record xTB
method, charge, UHF/unpaired setting, accuracy, electronic temperature, SCF
settings, constraints, and whether the branch is only `lower_level_minimum` or
`candidate_found`.

Move from xTB to Gaussian when:

- the candidate will be promoted to TS/Freq validation;
- endpoint references must support QST, Gaussian-NEB, IRC, or final
  connectivity checks;
- xTB changes connectivity, proton location, fragment identity, charge state, or
  spin/electronic character in a way that may be method-artificial;
- the reaction is HAT, PCET, radical, open-shell, metal-containing, strongly
  polar, or charge-transfer dominated;
- barrier height, imaginary mode, or endpoint assignment will be reported.

If xTB and Gaussian disagree, do not average them. Close or mark the branch
ambiguous, record the disagreement as evidence, and branch to a chemically
different endpoint/model/level hypothesis.

## Candidate Routes

### NEB

Use the bundled node-aware ASE framework for reusable xTB or explicit
Gaussian-force NEB candidate generation:

```bash
python scripts/ase_neb_framework.py validate-config examples/neb_xtb_config.json --strict-files
python scripts/ase_neb_framework.py prepare examples/neb_xtb_config.json
python scripts/ase_neb_framework.py run examples/neb_xtb_config.json
```

`prepare` creates a normalized `tssearch_<system>` workspace with
`manifest.json`, `tree.json`, `evidence_registry.json`, and node-scoped
artifacts. `run` may create `claim_status=candidate_found` only for NEB
candidates whose endpoint-validation parent is ready and that pass convergence,
non-endpoint, and minimum-barrier gates.

Promote an image only if:

- endpoint states are at least `lower_level_minimum` or clearly documented
  `constrained_reference` on both sides;
- NEB converged or convergence status is explicitly acceptable;
- the maximum is not an endpoint image;
- the barrier is nontrivial and not a zero-barrier artifact;
- the geometry has the intended reaction-center changes.

Choose xTB-NEB when endpoints are at least lower-level ready and the goal is
fast path discovery or candidate generation across several plausible reaction
coordinates. Choose Gaussian-force NEB only after endpoint identity is reliable
and xTB/scan/QST evidence points to a specific path worth the cost. A
Gaussian-force NEB maximum is still a candidate, not `tsfreq_validated`.

### Scan

A scan maximum is only a candidate. Use xTB scans for rapid coordinate testing
and rough barrier shape. Use Gaussian scans when the coordinate is chemically
central and xTB gives questionable connectivity, spin, charge, or proton/atom
placement. A scan maximum needs TS optimization and frequency validation. If the
scan coordinate forces the reaction unrealistically, reflect on coordinate
choice.

### QST2/QST3

QST is useful when optimized endpoints and a reasonable guess exist. It can converge to a different saddle or endpoint-side soft mode; check imaginary mode and connectivity.

### Dimer

Use when a local saddle is suspected but endpoint mapping is uncertain. xTB can
screen local saddle directions cheaply; Gaussian dimer/refinement is reserved
for candidates that remain chemically plausible on the DFT surface. Still
validate with Gaussian TS/Freq and connectivity.

### xTB

xTB is for low-cost candidate generation and screening. Do not report xTB-only TSs as final. Preserve xTB logs and geometries as candidate evidence.

xTB method and precision are branch variables, not global defaults. Vary GFN
method, accuracy, SCF iteration limit, electronic temperature, constraints,
image count, climbing-image setting, interpolation, and optimizer only as
explicit `changed_variables` in the node. If xTB requires strong constraints to
preserve endpoint identity, mark the result as `constrained_reference`, not a
validated minimum.

Run xTB from `nodes/<node_id>/outputs`, not the workspace root. xTB writes
fixed-name files such as `xtbopt.xyz`, `xtb.trj`, `xtbrestart`, `charges`,
`wbo`, `gradient`, and `hessian` into the current working directory. Running
from the node output directory is what keeps those artifacts attributable to
the branch that produced them.

Prefer the node-scoped wrapper for local or already-staged remote runs:

```bash
python scripts/ts_node_exec.py \
  --workspace /path/to/tssearch_system \
  --node-id n120_xtb_candidate \
  -- xtb ../inputs/candidate.xyz --opt --chrg <charge> --uhf <unpaired>
```

For ASE-driven NEB/scan/dimer workflows, set the script working directory or
trajectory/log output paths to `nodes/<node_id>/outputs` and write parsed
summaries under `nodes/<node_id>/parsed`.

For an existing image path that should be refined with Gaussian forces, use the
explicit external-Gaussian mode and start with `--dry-run-inputs`:

A prior NEB node writes its images to `nodes/<node_id>/images/` as
`initial_image_NN.xyz` and `final_image_NN.xyz` (both prefixes share that
directory). To refine the converged path, point `--xyz-dir` at it and select the
`final_image_*.xyz` set so the initial guess is not mixed in:

```bash
python scripts/ase_neb_framework.py continue-gaussian-neb-from-images tssearch_gaussian_refine \
  --xyz-dir nodes/n010_neb_xtb/images \
  --pattern 'final_image_*.xyz' \
  --route '# HF/sto-3g force nosymm' \
  --charge 0 --multiplicity 1 \
  --reactant-endpoint-state validated_minimum \
  --product-endpoint-state validated_minimum \
  --dry-run-inputs
```

Declare `--reactant-endpoint-state`/`--product-endpoint-state` (and optionally
`--endpoint-level`/`--endpoint-evidence`) to match the endpoint readiness already
established upstream; the candidate-promotion gate stays closed while either
endpoint is only a `reference_hypothesis`.

## Candidate Promotion

Create a Gaussian validation child node only when the candidate is chemically plausible:

- endpoints were distinct and endpoint identity was not produced solely by an
  arbitrary fragment pose;
- reaction-center bonds are between endpoint values;
- not an endpoint or conformational artifact;
- charge/multiplicity and atom order are correct;
- for open-shell cases, spin/electronic state is plausible.

If candidate quality is weak but informative, close the branch with reflection and branch from a mechanism ancestor.
