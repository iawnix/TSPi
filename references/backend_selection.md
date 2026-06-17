# Method And Level Selection

Use this reference when deciding how to search for a transition-state candidate
and which potential surface or execution backend should support that search.
For mechanism-analysis evidence limits, read
`references/mechanism_analysis_sources.md`. For low-to-high transfer of
candidates, read `references/refinement_ladder.md`.

Do not choose a method from a flat list. Choose the search strategy first, then
the level/backend that can run that strategy at the required cost and
reliability.

## Orthogonal Decisions

Keep these four decisions separate in every decision card:

- `stage`: endpoint discovery, candidate generation, candidate refinement,
  TS/Freq validation, connectivity validation, or mechanism acceptance.
- `search_strategy`: manual TS guess plus TS optimization, relaxed scan,
  constrained scan, NEB/CI-NEB/string/GSM, dimer/eigenvector following, QST2,
  QST3, reaction-network exploration, or MECP/dMECP.
- `level_backend`: xTB/GFN, semiempirical, Gaussian-External-xTB, Gaussian-force calculator, DFT/Gaussian, QBICS, or another explicitly documented engine.
- `claim_ceiling`: the highest scientific claim the result may support.

xTB, semiempirical methods, Gaussian-External-xTB, and Gaussian-force execution are levels/backends.
They are not search strategies. A branch should say `xTB scan`, `xTB NEB`,
`Gaussian-force NEB`, `Gaussian-External-xTB TS optimization`, or `DFT TS
optimization`, not simply "use xTB" or "use Gaussian".

## Stage-First Selection

| Information state | Next stage | Search strategy options | Level/backend options | Claim ceiling |
| --- | --- | --- | --- | --- |
| R/P structures are missing, unstable, or only rough poses | endpoint discovery | conformer search, pose search, constrained endpoint optimization | xTB/GFN, semiempirical, light DFT | endpoint hypothesis or endpoint readiness |
| R/P are plausible and one coordinate dominates | candidate generation | relaxed scan or constrained scan | xTB/GFN, semiempirical, Gaussian-External-xTB, DFT/Gaussian | `candidate_found` |
| R/P are plausible and path motion is multi-coordinate | candidate generation | NEB, CI-NEB, string, or GSM | xTB/GFN, Gaussian-force, DFT/Gaussian when justified | `candidate_found` |
| A structure is already near a saddle but endpoint path is uncertain | candidate generation | dimer or eigenvector-following | xTB/GFN for screening, DFT/Gaussian for targeted refinement | `candidate_found` |
| A chemically plausible TS guess exists | candidate refinement or validation | direct TS optimization | xTB/GFN, Gaussian-External-xTB, DFT/Gaussian | candidate at low level; `tsfreq_validated` only after high-level TS/Freq gates |
| R/P are reliable but a TS guess is hard to construct manually | candidate generation fallback | QST2, rarely QST3 | usually DFT/Gaussian or a documented lower level | `candidate_found` until TS/Freq gates pass |
| Mechanism or elementary steps are unknown | pathway discovery | AFIR, GRRM, GSM, metadynamics, or reaction-network exploration | engine-specific | pathway/candidate hypotheses |
| Crossing or diabatic-state hypothesis is central | crossing candidate generation | MECP or dMECP | QBICS or another crossing backend | crossing/candidate evidence only |
| Low-level candidate exists and looks chemically plausible | candidate refinement | high-level TS optimization seeded from candidate | DFT/Gaussian | `tsfreq_validated` after TS/Freq gates |
| TS/Freq evidence exists | connectivity validation | mode-follow endpoint optimization, structural endpoint checks, IRC | DFT/Gaussian or documented same-level checks | `endpoint_connected` or `irc_connected` |

No candidate-generation strategy may set `claim_status=accepted_ts`. That
includes scan, NEB, string/GSM, dimer, QST, reaction-network exploration,
MECP/dMECP, xTB-backed searches, Gaussian-External-xTB, and Gaussian-force NEB.

## Search Strategy Rules

Manual TS guess plus direct TS optimization

- Use when a chemically plausible TS guess exists.
- At low level, this produces or improves a candidate.
- At target Gaussian/DFT level, it can support `tsfreq_validated` only when the
  Gaussian TS/Freq gates pass.
- It is not a global default starting point.

Relaxed or constrained scans

- Use when a dominant coordinate is chemically meaningful.
- Use xTB or semiempirical scans for breadth; use Gaussian scans when the
  coordinate is sensitive to spin, charge, proton placement, solvent, or
  electronic structure.
- A scan maximum is only a candidate seed.

NEB, CI-NEB, string, or GSM

- Use when endpoints are reliable enough and the elementary step is expected to
  involve multi-coordinate path motion.
- xTB NEB is appropriate for broad path discovery. Gaussian-force NEB is a
  refinement path when endpoints are reliable and lower-level path evidence is
  promising. DFT/Gaussian path methods should be justified by mechanism risk or
  small system size.
- The highest image or climbing image is a candidate seed, not a validated TS.

Dimer or eigenvector-following

- Use when the structure is near a saddle but the full endpoint path is unclear
  or too expensive to build.
- Low-level dimer is screening; high-level dimer/refinement still needs TS/Freq
  and connectivity checks.

QST2

- Use only as a limited fallback when the elementary step is clear, R/P
  structures are chemically plausible, atom order and mapping are reliable, and
  constructing a TS guess by scan/path/manual editing is not the better next
  move.
- Do not use QST2 merely because a previous `Opt=TS` failed.
- QST2 can generate a candidate, but the result still needs TS/Freq and
  connectivity validation.

QST3

- Generally avoid QST3. If a plausible TS guess already exists, direct TS
  optimization is usually the cleaner test.
- Use only with an explicit reason why R/P guidance plus a TS guess is expected
  to help more than direct TS optimization.

Reaction-network exploration

- Use when the mechanism or intermediate sequence is unknown.
- Treat discovered paths and structures as hypotheses. Split the result into
  elementary steps before making TS claims.

MECP or dMECP

- Use for crossing or diabatic-state hypotheses, not as a generic ground-state
  TS replacement.
- A crossing candidate still needs the appropriate validation path for the
  scientific claim being made.

## Level And Backend Rules

xTB/GFN and semiempirical levels

- Use for fast endpoint cleanup, conformer/pose screening, scan, NEB, dimer,
  and low-level TS-guess optimization.
- Record method, charge, unpaired/UHF setting, accuracy or convergence options,
  constraints, and changed variables.
- Treat the output as screening evidence unless it is explicitly refined and
  validated at the target level.

Gaussian-External-xTB

- Use when Gaussian's optimizer or frequency-style driver is useful but xTB is
  the intended low-cost surface.
- It can support low-level TS optimization, scans, or Hessian/gradient trials
  through Gaussian's External protocol.
- It is a level/backend choice, not a standalone search strategy.

Gaussian/DFT

- Use when the result will support endpoint readiness, TS/Freq validation,
  final barrier/electronic interpretation, or connectivity proof.
- Use the same intended level for endpoint references, TS refinement, and
  connectivity claims unless a mixed-level claim is explicitly marked
  `ambiguous` or screening-only.

Gaussian-force calculator

- Use as a backend for ASE NEB/string-like refinement when endpoints are
  reliable and lower-level path evidence justifies the cost.
- It remains candidate generation until a separate TS/Freq and connectivity
  branch passes.

QBICS dMECP

- Use as a backend for diabatic crossing candidate generation when fragment or
  state definitions are chemically meaningful.
- It does not produce ordinary `accepted_ts` claims by itself.

## Refinement Trigger

Move from low-level exploration to high-level refinement when:

- a candidate has the intended reaction-center geometry;
- atom mapping, charge, multiplicity, and fragment identities remain stable;
- the candidate is not an endpoint image, a conformer-only motion, or an
  artifact of imposed constraints;
- failure to validate the candidate would be informative.

When high-level refinement drifts away from the intended reaction center,
record the drift as evidence and backtrack to candidate generation, endpoint
definition, level choice, or mechanism decomposition. Do not treat one drifted
refinement as proof that the mechanism is impossible.
