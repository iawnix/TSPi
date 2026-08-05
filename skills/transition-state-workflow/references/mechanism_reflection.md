# Mechanism Reflection

Mechanism reasoning is explicit hypothesis management, not a hidden pipeline.

## Proposal

After intake, open `node_type=mechanism, mechanism_action=propose`. Derive the
hypothesis from verified structures, charge, multiplicity, atom mapping,
reaction-center changes, and explicitly labeled chemical assumptions.

Minimum hypothesis content:

- stable `hypothesis_id` and optional parent hypothesis;
- structure provenance;
- reaction center and elementary-step model;
- electronic and spin/state model;
- mechanism claims;
- testable predictions with `validation_scope`, expectation, and required
  evidence roles;
- uncertainties and alternative hypotheses;
- evidence refs.

Each proposal states what local geometry and electronic structure would be
consistent with the mechanism. Claims about intermediate identity, electron transfer, radical/diradical
character, excited states, oxidation state, carbene/nitrene/oxene identity,
zwitterions, ion pairs, or shared basins require explicit geometry and
electronic/state tests.

Example prediction:

```json
{
  "prediction_id": "pred_state_001",
  "validation_scope": "electronic_structure",
  "expectation": "Natural orbital occupations remain consistent with a closed-shell singlet.",
  "required_evidence_roles": ["electronic_structure_gate"]
}
```

## Local Geometry And Electronic Structure

Every candidate-generation and TS/Freq reflection must answer both questions:

1. Does the local geometry still match the declared reaction-center motif?
   Check neighbors, unintended short contacts, valence/coordination, key
   angles, folding, transferred atoms, and spectator drift.
2. Does available electronic structure contradict the hypothesis? Use
   method-appropriate charges, spin density, occupations, broken-symmetry or
   state comparisons, TD-state character, or charge-transfer diagnostics.

Population analyses are usually method-dependent sanity checks, not standalone
proof. State the decision boundary in the prediction before treating a result
as contradictory.

If geometry or electronic evidence contradicts the hypothesis, keep useful
artifacts but do not describe the structure as a plausible seed and do not
start connectivity work from it. Open a mechanism evaluation node to assign
the hypothesis status.

## Validation Then Interpretation

Use separate validation scopes:

- `geometry_identity` for local motif or basin identity;
- `electronic_structure` for populations, orbitals, occupations, and bonding;
- `state_character` for spin, open-shell, broken-symmetry, excited-state, or
  nonadiabatic character;
- `tsfreq` for stationary point, frequency, and mode assignment;
- `connectivity` for displacement/IRC endpoint assignment;
- `thermochemistry` for electronic, ZPE, thermal, and free-energy evidence;
- `method_robustness` for method-sensitive conclusions.

Validation closure records program facts and evidence only. A later
`mechanism, mechanism_action=evaluate` node compares those facts with the
prediction and sets:

- `supported`: evidence satisfies the declared boundary;
- `unsupported`: evidence contradicts it;
- `ambiguous`: missing, weak, or conflicting evidence.

## Identity And Multi-Step Pathways

Connectivity says where a path lands. It does not by itself prove what the
basin is. When the hypothesis names an intermediate or shared basin, add
identity, minimum, electronic/state, and shared-basin evidence as applicable.

For a multi-step pathway, the intermediate reached from TS1 and used for TS2
must be demonstrated to be the same basin under declared identity criteria.

Only add stereochemical policy when stereoisomer identity matters. Once
declared, the accepted audit must include the matching stereochemical gate.

## Revisions And Alternatives

When evidence contradicts a prediction:

1. close the validation node with program facts;
2. open a mechanism evaluation node;
3. cite the contradictory evidence;
4. set hypothesis status and record the changed variable;
5. decide whether to revise, propose an alternative, recalculate, branch, ask
   the user, or stop.

An alternative hypothesis is another `mechanism/propose` node with a new ID,
known parent hypothesis, cited evidence, and
`relation=new_hypothesis_branch`. Validators never create it automatically.

Read `references/strategy_reflection.md` after repeated wrong-basin, route-
ineffective, same-side IRC, surface ambiguity, or route-mismatch failures.

## Reporting

Separate:

- accepted pathway evidence;
- mechanistic interpretation;
- alternative explanations;
- absent electronic/state diagnostics;
- method dependence.

Geometry-only connectivity must not be presented as proof of electronic timing
or intermediate identity.
