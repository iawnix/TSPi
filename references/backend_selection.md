# Backend Selection

Use this reference when choosing between xTB, ASE, Gaussian, QBICS, and
Gaussian-External-xTB. For mechanism-analysis evidence limits, read
`references/mechanism_analysis_sources.md`.

Backend choice is a chemistry decision, not a fixed pipeline. Start from the
mechanism hypothesis, the endpoint evidence already available, the reaction
center that must move, and the evidence layer needed next.

## Evidence Layers

Use the lowest-cost backend that can answer the current question, then escalate
when the claim needs stronger evidence.

| Needed evidence | Suitable backends | Claim ceiling |
| --- | --- | --- |
| Endpoint cleanup or pose screening | xTB/GFN, constrained xTB, light Gaussian optimization | endpoint readiness or screening evidence |
| Path or saddle candidate | xTB scan, xTB/ASE NEB, dimer, QST guess, QBICS dMECP, Gaussian-External-xTB | `candidate_found` |
| Stationary-point and imaginary-mode validation | Gaussian DFT TS/Freq | `tsfreq_validated` |
| Endpoint-side proof | mode displacement plus endpoint optimization, IRC, structural endpoint checks | `endpoint_connected` or `irc_connected` |
| Final elementary-step acceptance | Gaussian TS/Freq plus connectivity validation | `accepted_ts` |

No candidate-generation backend may set `claim_status=accepted_ts`. This
includes xTB, ASE, NEB, QST guesses, dimer searches, QBICS dMECP, and
Gaussian-External-xTB.

## Backend Rules

Direct Gaussian DFT `Opt=(TS,CalcFC,NoEigen) Freq`

- Use when a chemically plausible TS guess exists and the result will support
  stationary-point or imaginary-mode evidence.
- Prefer this for open-shell, HAT, PCET, metal-containing, charge-transfer, or
  electronically delicate branches.
- A passing TS/Freq job still needs endpoint/connectivity validation before
  `accepted_ts`.

Gaussian-External-xTB

- Use when Gaussian optimizer behavior is useful but the branch still belongs
  to low-cost screening.
- Useful for testing TS optimizer behavior, Hessian availability, and rough
  reaction-center motion before spending DFT cost.
- Requires `NoMicro` and node-scoped artifact directories.
- Treat every output as candidate/search evidence only; promising structures
  must branch to Gaussian DFT TS/Freq and connectivity validation.

xTB/GFN direct runs

- Use for endpoint preoptimization, conformer or fragment-pose screening,
  constrained references, relaxed scans, and quick branch triage.
- Record method, charge, UHF/unpaired setting, accuracy, electronic
  temperature, constraints, and fixed-name artifacts.
- Escalate when xTB changes connectivity, proton location, fragment identity,
  spin/charge state, or barrier interpretation.

ASE/xTB scan, NEB, or dimer

- Use when a continuous low-cost path or local saddle direction is the next
  question.
- NEB requires endpoint readiness; do not start from arbitrary R/P pose
  differences.
- The highest image, scan maximum, or dimer geometry is only a candidate.

Gaussian-force NEB

- Use only after endpoint identity is reliable and cheaper path evidence points
  to a specific path worth refining.
- It is more expensive candidate generation, not a substitute for TS/Freq.

QST2/QST3

- Use QST2 when optimized endpoints are distinct and mapped.
- Use QST3 when endpoints plus a chemically plausible TS guess are available.
- Check the imaginary mode and connectivity; QST convergence can still land on
  the wrong saddle or an endpoint-side soft mode.

QBICS dMECP

- Use when diabatic fragment definitions are chemically meaningful for atom
  transfer, bond switching, or related crossing-point hypotheses.
- It is candidate-generation evidence. A dMECP geometry still needs Gaussian
  TS/Freq and connectivity validation before mechanism acceptance.

## Escalation Triggers

Move to Gaussian DFT validation when any of these are true:

- the branch will support `tsfreq_validated`, `endpoint_connected`,
  `irc_connected`, or `accepted_ts`;
- the mechanism depends on spin, charge migration, orbital character, or final
  barrier height;
- lower-level methods disagree with endpoint identity or reaction-center
  chemistry;
- the candidate is good enough that failure to validate it would be useful
  evidence.

Backtrack instead of escalating when the endpoints are not distinct, endpoint
optimization collapses the intended sides, or the candidate is an endpoint or
conformational artifact.
