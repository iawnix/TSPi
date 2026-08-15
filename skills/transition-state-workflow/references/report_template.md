# Report Contract

Build the standard report from a valid v3 workspace. A custom narrative may add
chemistry-specific tables and figures, but it must preserve the same authority
boundaries.

## Required Sections

1. Workspace revision and report identity.
2. Focus Claims with kind, statement, status, required Gates, and limitations.
3. Deterministic Gate results with policy, target, Evidence refs, verdict, and
   diagnostics.
4. Active Evidence with kind, tier, owner Node, facts, provenance, and artifacts.
5. Research Nodes with parent, objective, tags, state, outcome, and open
   questions.
6. Accepted artifacts with policy, target Claim, Gate-result refs, and decision.
7. Operational follow-up, including unresolved controls and pending Review
   responses.

Keep electronic energy, E+ZPE, enthalpy, and free energy distinct and label
units and reference states. State missing corrections rather than silently
substituting another quantity.

## Acceptance Language

Use accepted-transition-state language only when an accepted artifact exists for
the target Claim under `accepted-ts/2`. Cite the passing TS/Freq and
connectivity Gate results and any optional Gates actually included. Do not infer
acceptance from a Node tag, one imaginary frequency, normal program termination,
or an advisory Review.

Use accepted-pathway language only for an accepted artifact under
`accepted-pathway/1`. Report untested steps, finite IRC endpoints, method
limitations, and unresolved alternative Claims explicitly.

Every number or structure claim should cite a registered Evidence ref and its
source artifact. Review/operator journals and notification receipts are
operational provenance and must not appear as scientific Evidence.
