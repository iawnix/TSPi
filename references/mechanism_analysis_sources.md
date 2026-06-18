# Mechanism Analysis Evidence Sources

Use this reference when a branch needs structured `mechanism_analysis` records.
Every record must come from a concrete file, parsed descriptor, or explicit
absence of evidence. Attach that provenance either through the same
`end_node --evidence` records or through the per-record `source` field.
Do not infer electronic, orbital, or energy descriptors from method names,
route text, filenames, or neighboring branches.

Before evidence exists, put required diagnostics in the hypothesis-stage
`analysis_plan`. Promote only source-backed observations to
`mechanism_analysis`.

## Analysis Layers

Mechanism-analysis records use these layers:

- `reaction_type`: elementary mechanism class and competing-class exclusion.
- `reaction_center`: mapped atoms, forming/breaking bonds, angles, fragments,
  and imaginary-mode participation.
- `electronic`: charge, multiplicity, `<S^2>`, spin density, donor/acceptor
  charge movement, and state consistency.
- `orbital`: frontier orbital, occupation, population, or NBO/NPA-style
  descriptors.
- `energy`: endpoint energy, TS energy, barrier, reaction energy, and barrier
  shape.

Use these statuses:

- `hypothesis`: expected before direct evidence exists.
- `supported`: directly supported by cited evidence.
- `refuted`: directly contradicted by cited evidence.
- `ambiguous`: mixed or insufficient evidence.
- `unavailable`: the required output section or calculation was not produced.

Each record should also include a source:

- use `source` for the direct output or parsed descriptor behind that analysis
  layer, especially when no same-finalization evidence record is attached;
- use `metrics` only for compact numeric descriptors that were actually parsed;
- use `details` for method, route, population scheme, caveats, or screening
  labels that are needed to interpret the source.

## Method Capability Matrix

| Method or artifact | reaction_type | reaction_center | electronic | orbital | energy |
| --- | --- | --- | --- | --- | --- |
| Preflight from atom mapping and endpoints | hypothesis from mapped bond changes | mapped atoms, expected bonds and angles | charge/multiplicity hypothesis only | unavailable | unavailable or endpoint estimate only |
| xTB/GFN optimization | supported only as low-level trend | key bonds, fragments, WBO proxy | charges and UHF/unpaired setting as screening evidence | unavailable unless separate output exists | rough relative energy only |
| xTB scan/NEB/dimer | candidate-level path class | scan coordinate, highest image, WBO/bond changes | screening-level charges/spin setting | unavailable | rough barrier shape, not final barrier |
| ASE NEB with xTB forces | candidate path only | image sequence and max-image geometry | inherited from engine, usually screening only | unavailable | relative image energies at chosen engine |
| Gaussian-External-xTB | candidate-level optimizer or Hessian trial | Gaussian-driven trial geometry and xTB gradient/Hessian response | xTB charge and UHF setting as screening evidence | unavailable | xTB energy and curvature only, not final barrier |
| Gaussian endpoint optimization/frequency | endpoint identity and minimum status | optimized endpoint bonds, angles, fragments | charge/multiplicity, `<S^2>`, population if requested | only if route requests orbital/population output | endpoint energy and thermochemistry |
| Gaussian TS/Freq | TS class only after mode inspection | imaginary mode, TS geometry, mode participation | charge/multiplicity, `<S^2>`, population if requested | only if route requests orbital/population output | TS energy and thermochemistry |
| Gaussian displacement endpoint optimization | endpoint-side assignment | plus/minus endpoint structures and key bonds | output-level charge/spin if requested | only if route requests orbital/population output | endpoint-side energies at same level |
| Gaussian IRC | connection class after endpoint checks | forward/reverse path and optimized endpoint assignment | output-level charge/spin if requested | usually unavailable unless requested | path profile and endpoint energies |
| Gaussian Pop/NBO/NPA follow-up | not by itself | not by itself | charge, spin, population, donor/acceptor migration | orbital occupation, NBO/NPA/frontier descriptors | same-point energy if present |
| QBICS dMECP | diabatic fragment hypothesis for atom transfer or bond switching | fragment and crossing-point geometry | diabatic-state screening only | method-specific, not accepted-TS proof | crossing/candidate energy only |

## Gaussian Output Sources

Use Gaussian for any final electronic, orbital, or energy claim. Route keywords
control what is available:

- Basic TS/Freq evidence: `Opt=(TS,...) Freq` gives stationary-point, frequency,
  geometry, energy, and thermochemistry evidence.
- Open-shell diagnostics: unrestricted methods expose `<S^2>` lines; compare
  before and after annihilation when present.
- Charge or spin distribution: request population output such as `Pop=Full`,
  `Pop=MK`, `Pop=Hirshfeld`, or a project-approved population analysis. Record
  the exact population scheme.
- Orbital descriptors: request orbital eigenvalue/occupation output, or a
  supported NBO/NPA route if installed. If the output lacks those sections,
  record `orbital` as `unavailable`.
- Energy profile: use the same method, basis, dispersion, solvent, charge, and
  multiplicity for endpoints and TS. Mark mixed-level barriers as `ambiguous`
  unless the branch explicitly labels them as screening evidence.

Useful bundled commands:

```bash
python scripts/parse_gaussian_ts_result.py \
  nodes/n230_gaussian_tsfreq/outputs/candidate_tsfreq.out \
  -o nodes/n230_gaussian_tsfreq/parsed --strict

python scripts/ts_imaginary_mode_follow.py prepare \
  nodes/n230_gaussian_tsfreq/outputs/candidate_tsfreq.out \
  --workspace tssearch_<system> \
  --node-id n240_imaginary_follow \
  --template-gjf nodes/n230_gaussian_tsfreq/inputs/candidate_tsfreq.gjf \
  --scale 0.25

python scripts/ts_descriptor_extract.py \
  --ts-out nodes/n230_gaussian_tsfreq/outputs/candidate_tsfreq.out \
  --ts-xyz nodes/n240_imaginary_follow/outputs/ts_final.xyz \
  --minus-xyz nodes/n240_imaginary_follow/outputs/mode_minus.xyz \
  --plus-xyz nodes/n240_imaginary_follow/outputs/mode_plus.xyz \
  --pairs 4-12 7-15 \
  -o nodes/n240_imaginary_follow/parsed
```

## xTB, ASE, and Gaussian-External-xTB Candidate Sources

xTB, ASE path tools, and Gaussian-External-xTB are valuable for choosing
branches, not final electronic, orbital, or barrier proof.

Record as `supported` only for candidate-level observations:

- reaction-center distances or WBO trends;
- whether a scan/NEB maximum is internal rather than an endpoint image;
- rough barrier shape and reaction coordinate plausibility;
- endpoint collapse, wrong proton site, or fragment identity loss.

Record as `ambiguous` or `unavailable` for:

- final orbital mechanism;
- final spin-density migration;
- final barrier or reaction energy;
- accepted-TS proof.

The usual mechanism-analysis records from xTB/ASE/Gaussian-External-xTB are
`reaction_center`, `energy` with a screening qualifier, and occasionally
`reaction_type` as a hypothesis. Move to Gaussian DFT validation when the branch
needs final electronic, orbital, frequency, or barrier evidence.

## QBICS dMECP Sources

QBICS dMECP can support a diabatic candidate-generation hypothesis when the
fragment definition is chemically meaningful.

Use it for:

- `reaction_type=hypothesis` when atom transfer or bond switching is plausible;
- `reaction_center=supported` for fragment geometry and bond switching at the
  candidate point;
- `energy=ambiguous` or `hypothesis` for crossing-point screening.

Do not use QBICS dMECP alone for `accepted_ts`, final orbital analysis, or final
barrier claims. A dMECP candidate still needs Gaussian TS/Freq and connectivity
validation before mechanism acceptance.

## Recording Templates

Supported reaction-center record:

```json
{
  "layer": "reaction_center",
  "status": "supported",
  "summary": "The imaginary mode moves H7 along the O1-H7-N3 coordinate and changes both donor and acceptor distances.",
  "source": "nodes/n240_imaginary_follow/parsed/ts_descriptors.json",
  "metrics": {
    "O1_H7_delta_angstrom": 0.31,
    "N3_H7_delta_angstrom": -0.28
  }
}
```

Unavailable orbital record:

```json
{
  "layer": "orbital",
  "status": "unavailable",
  "summary": "The Gaussian TS/Freq output did not include orbital or population sections; no orbital interpretation is made.",
  "source": "nodes/n230_gaussian_tsfreq/outputs/candidate_tsfreq.out"
}
```

Screening energy record:

```json
{
  "layer": "energy",
  "status": "hypothesis",
  "summary": "xTB-NEB gives a nonzero internal barrier shape; this is screening evidence only and needs Gaussian validation.",
  "source": "nodes/n120_xtb_neb/parsed/neb_summary.json",
  "metrics": {
    "barrier_ev_xtb": 0.42
  },
  "details": {
    "reliability": "screening"
  }
}
```

## Promotion Rules

- `candidate_found`: may record geometry and low-level energy trends, but final
  electronic, orbital, and barrier claims should be `hypothesis`, `ambiguous`,
  or `unavailable`.
- `tsfreq_validated`: may record TS geometry, imaginary-mode participation,
  same-output energy, and available electronic/orbital descriptors.
- `endpoint_connected` or `irc_connected`: may record endpoint assignment,
  reaction energy, and path-level reaction-center support.
- `accepted_ts`: should have enough mechanism analysis to explain why the TS
  belongs to the intended elementary step. For open-shell, HAT, PCET,
  charge-transfer, spin-crossover, or electronically delicate cases, include
  electronic diagnostics or an explicit reason they are unavailable.
