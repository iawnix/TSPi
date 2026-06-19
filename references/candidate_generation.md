# Candidate Generation

Use this for generating transition-state candidates before final validation.
For method choice, read `references/backend_selection.md`. For low-level to
high-level candidate transfer, read `references/refinement_ladder.md`. For
mechanism-analysis records from candidate-generation methods, read
`references/mechanism_analysis_sources.md`.

Candidate generation chooses a search strategy first, then a level/backend.
Examples are `xTB scan`, `DFT scan`, `xTB NEB`, `Gaussian-force NEB`,
`Gaussian-External-xTB TS optimization`, and `DFT dimer`. Do not describe
xTB/GFN, semiempirical methods, Gaussian-External-xTB, or Gaussian-force
execution as standalone search strategies.

## Endpoint Rule

Treat supplied reactant and product structures as reference endpoint
hypotheses until proven otherwise. Optimize or stabilize endpoints before path
searches. For NEB, string, GSM, and QST especially, unreliable endpoints can
create artificial paths, endpoint barriers, wrong highest-energy images, or
invalid interpolated guesses.

For two-molecule, multicomponent, ion-pair, encounter-complex, or flexible
systems, do not assume the supplied relative pose is a minimum. First check
fragment identity, reaction-center bonds/angles, and whether each side remains
distinct during optimization. Whole-system RMSD is secondary unless the
intended chemistry requires a specific bound complex pose.

Endpoint states:

- `validated_minimum`: optimized at the intended level and distinct.
- `lower_level_minimum`: optimized at xTB or another cheaper level, still
  awaiting intended-level confirmation.
- `constrained_reference`: optimized with light, chemically justified
  constraints to preserve endpoint identity.
- `reference_hypothesis`: supplied or drawn geometry, not yet a minimum.
- `collapsed_or_unstable`: optimization changes side, merges R/P, dissociates,
  or loses the intended reaction-center identity.

Allowed ready states for candidate promotion are `validated_minimum`,
`lower_level_minimum`, and `constrained_reference` on both sides. The default is
`reference_hypothesis`, which lets `prepare` record the branch but prevents
promotion to `candidate_found`.

Do not run NEB, string/GSM, QST, or Gaussian-force NEB from endpoints that are
not distinct on the chosen surface unless the branch is explicitly endpoint
discovery or constrained candidate generation.

Record:

- search strategy and level/backend;
- method, charge, multiplicity, solvent, dispersion, and constraints;
- endpoint state and evidence;
- final or candidate energy at that level;
- key reaction-center bonds/angles;
- fragment identity and relative-pose assumptions;
- changed variables from the parent branch.

## Search Strategies

### Manual Guess Plus TS Optimization

Use when a chemically plausible TS guess exists. At low level this is candidate
generation or candidate cleanup. At target Gaussian/DFT level it is candidate
refinement and may become `tsfreq_validated` only after Gaussian TS/Freq gates
pass.

Available level/backend choices include:

- xTB/GFN or semiempirical for fast TS-guess cleanup;
- Gaussian-External-xTB when Gaussian's TS optimizer behavior is useful on an
  xTB surface;
- DFT/Gaussian when validating or refining a plausible candidate.

This route is not a global default starting point. It tests a specific TS
candidate.

### Relaxed Or Constrained Scan

Use when a dominant coordinate is chemically meaningful, such as proton
transfer, bond stretch, bond formation, angle-controlled rearrangement, or a
small set of coupled coordinates.

Use xTB/GFN or semiempirical scans for rapid coordinate testing and rough
barrier shape. Use Gaussian/DFT scans when spin, charge, solvent, proton
placement, or electronic structure is central to the coordinate. A scan maximum
is only a candidate seed and needs TS optimization plus frequency validation.

If the scan coordinate forces the reaction unrealistically, close the branch or
mark it `ambiguous` and choose a different coordinate or path strategy.

### NEB, CI-NEB, String, Or GSM

Use when endpoints are reliable and the intended elementary step likely needs a
multi-coordinate path. Do not use path methods for a total R->P transformation
that likely contains intermediates; split the pathway into elementary steps.

Use xTB NEB or string/GSM for broad path discovery. Use Gaussian-force NEB only
after endpoint identity is reliable and lower-level path evidence points to a
specific path worth the cost. DFT/Gaussian path searches should be justified by
small system size or high electronic sensitivity.

Promote an image only if:

- endpoint states are at least `lower_level_minimum` or clearly documented
  `constrained_reference` on both sides;
- the path converged or the convergence status is explicitly acceptable for
  candidate generation;
- the maximum is not an endpoint image;
- the barrier is nontrivial and not a zero-barrier artifact;
- the geometry has the intended reaction-center changes.

The highest image or climbing image is still a candidate, not
`tsfreq_validated`.

Bundled ASE framework example:

```bash
python scripts/ase_neb_framework.py validate-config examples/neb_xtb_config.json --strict-files
python scripts/ase_neb_framework.py prepare examples/neb_xtb_config.json
python scripts/ase_neb_framework.py run examples/neb_xtb_config.json
```

Remote ASE/xTB NEB should go through the generic remote job CLI rather than a
hand-written runner. Put the config and endpoint XYZ files under the intended
node `inputs/` directory, then submit the node-scoped job:

```bash
python scripts/ts_remote_job.py submit --engine ase-neb \
  --config nodes/n030_xtb_neb/inputs/ase_neb_xtb_config.json \
  --root /home/iaw/codex_runs/TEST4/tssearch_example \
  --node n030_xtb_neb \
  --login-host iaw.1w \
  --compute-host compute-0-30 \
  --background
```

The adapter uploads a runtime copy to
`<remote-root>/tools/transition-state-workflow/`, rewrites the remote config so
input paths and the nested ASE-NEB output directory are node-scoped, and records
metadata/logs under `nodes/<node>/outputs/`. Monitor and fetch with:

```bash
python scripts/ts_remote_job.py status --engine ase-neb --root <remote-root> --node n030_xtb_neb --login-host iaw.1w --compute-host compute-0-30
python scripts/ts_remote_job.py tail --engine ase-neb --root <remote-root> --node n030_xtb_neb --login-host iaw.1w --compute-host compute-0-30 --file auto
python scripts/ts_remote_job.py fetch --engine ase-neb --root <remote-root> --node n030_xtb_neb --login-host iaw.1w --compute-host compute-0-30 --local-root .
```

To refine an existing image path with Gaussian forces, first dry-run the inputs:

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

### Dimer Or Eigenvector Following

Use when a local saddle is suspected but endpoint mapping or the full path is
uncertain. xTB/GFN can screen local saddle directions cheaply. DFT/Gaussian
dimer or refinement is reserved for candidates that remain chemically
plausible on the target surface.

Still validate with Gaussian TS/Freq and connectivity.

### QST2 And QST3

Use QST2 only as a limited fallback when the elementary step is clear, R/P
structures are chemically plausible, atom order and mapping are reliable, and a
manual/scan/path TS guess is not the better next move. Do not use QST2 merely
because a previous TS optimization failed.

Generally avoid QST3. If a plausible TS guess already exists, direct TS
optimization is usually the cleaner branch. Use QST3 only with an explicit
reason why R/P guidance plus a TS guess should help.

QST convergence can still land on the wrong saddle or an endpoint-side soft
mode; check the imaginary mode and connectivity.

### Reaction-Network Exploration

Use AFIR, GRRM, GSM, metadynamics, or other network/path discovery tools when
the mechanism, intermediates, or elementary-step sequence is unknown. Treat
outputs as pathway hypotheses and candidate seeds. Split the discovered route
into elementary steps before TS/Freq validation.

### MECP Or dMECP

Use MECP or dMECP when crossing or diabatic-state hypotheses are chemically
central. QBICS dMECP is candidate-generation evidence for those hypotheses; it
does not by itself validate an ordinary ground-state TS.

## Level And Backend Examples

xTB/GFN and semiempirical levels can support endpoint cleanup, scans, NEB,
dimer, and low-level TS-guess optimization. Preserve fixed-name xTB artifacts
by running from `nodes/<node_id>/outputs`:

```bash
python scripts/ts_node_exec.py \
  --workspace /path/to/tssearch_system \
  --node-id n120_xtb_candidate \
  -- xtb ../inputs/candidate.xyz --opt --chrg <charge> --uhf <unpaired>
```

Gaussian-External-xTB can support Gaussian-driven low-cost TS optimization,
gradient/Hessian trials, or other External-compatible screening jobs on the xTB
surface:

```bash
python scripts/gaussian_external_xtb.py --help
```

Read `references/gaussian_external_xtb.md` before preparing an External route.

## Candidate Promotion

Create a high-level refinement or Gaussian validation child node only when the
candidate is chemically plausible:

- endpoints were distinct and endpoint identity was not produced solely by an
  arbitrary fragment pose;
- reaction-center bonds are between endpoint values or otherwise TS-like;
- the candidate is not an endpoint or conformational artifact;
- charge/multiplicity and atom order are correct;
- for open-shell cases, spin/electronic state is plausible;
- constraints used during candidate generation are documented and either
  removed or justified for the refinement branch.

If candidate quality is weak but informative, close the branch with reflection
and branch from a mechanism ancestor.
