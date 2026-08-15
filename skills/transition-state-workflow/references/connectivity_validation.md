# Connectivity Validation

Connectivity validation tests whether a transition-state candidate connects the
two sides declared by the target Claim. Keep its Evidence separate from
TS/Freq Evidence even when one calculation campaign produced both.

## Required Basis

Use explicit, locally verified facts where applicable:

- atom mapping and element-preserving identity;
- reaction-center bond distances, angles, and dihedrals;
- whole-structure and reaction-center RMSD after proper-rotation alignment;
- conformer and stereochemical criteria declared by the target Claim;
- forward and reverse IRC completion and endpoint structures;
- endpoint optimization or independent fragment minima when a finite IRC
  endpoint is not the intended asymptote.

An IRC endpoint assignment proves basin connectivity only under the selected
method and settings. It does not automatically prove electronic identity,
oxidation state, charge localization, spin character, excited-state character,
intermediate identity, or a shared basin between adjacent steps.

## Deterministic Gates

The `connectivity` Gate evaluates active `local_parse` Evidence and requires:

- `normal_termination=true`;
- `strict_irc_complete=true`;
- no `irc_program_failures`;
- normal termination and a nonempty assignment for both forward and reverse
  directions.

The Evidence facts must contain those policy paths exactly. Descriptive fields
may add distances, mappings, endpoint labels, finite-path limitations, and
diagnostics, but they do not replace the required facts.

Use additional current Gate names only when the Claim or audit requires them:

- `stereochemistry`: `stereochemistry_matched=true` and an empty
  `stereochemical_mismatches` list;
- `endpoint_identity` or `intermediate_identity`:
  `identity_supported=true`;
- `electronic_structure`: normal termination plus
  `electronic_structure_supported=true`;
- `state_character`: normal termination plus
  `state_character_supported=true`;
- `shared_basin_consistency`: `shared_basin_consistent=true`.

These are Gate names, not Evidence roles, Node types, or required workflow
stages. The Root Agent declares relevant Gates on the Claim and evaluates them
through ordinary Decisions after their facts exist.

## Finite IRC Endpoints

An IRC limited by `MaxPoints` may end at a finite-distance encounter structure.
That is not automatically an error and must not be described as numerical
infinite separation. Record:

- whether the path and selected endpoint optimization terminated normally;
- the disconnected molecular graph and conformer identity at the finite
  endpoint;
- any residual intermolecular distance or interaction;
- how independent fragment minima define the separated asymptote;
- the limitation that the computed endpoint is finite.

The Root Agent decides whether these facts satisfy the target Claim and any
additional endpoint-identity requirement. Do not hide the finite-path boundary
inside a generic `connected=true` summary.

## Acceptance

`accepted-ts/2` requires current, passing, target-compatible `tsfreq` and
`connectivity` Gate results. Other Gates are optional at the audit-policy level
but become mandatory when the target Claim lists them in `required_gates` or
the scientific interpretation depends on them.

Do not infer connectivity acceptance from a rendered image, one endpoint,
normal program termination, scheduler completion, or advisory Review. Register
the verified facts as normal Evidence, evaluate the named Gate, and cite that
Gate result in the explicit Claim update or audit.
