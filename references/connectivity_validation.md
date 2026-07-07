# Connectivity Validation

Connectivity validation checks whether a TS candidate connects the intended
endpoints or pathway step sides.

Use explicit evidence:

- atom mapping;
- reaction-center bond distances;
- key angles and dihedrals;
- local and heavy-atom RMSD;
- conformer policy;
- stereochemical policy;
- endpoint optimization or IRC when required.

Connectivity evidence should be registered separately from TS/Freq evidence.
Accepted TS audit requires both layers.

IRC endpoint assignment proves basin connectivity under the chosen method and
settings. It does not by itself prove an endpoint's electronic identity,
intermediate identity, radical/open-shell character, excited-state character,
oxidation state, zwitterionic character, or a shared intermediate basin between
two elementary steps. If the hypothesis declares those mechanism claims, record
separate `endpoint_identity_gate`, `intermediate_identity_gate`,
`electronic_structure_gate`, `state_character_gate`, or
`shared_basin_consistency_gate` evidence before accepted/pathway audit language
is allowed.

If a hypothesis has stereochemical requirements, declare them in
`structured_claim.stereochemical_policy`,
`structured_claim.stereochemical_requirements`, or by listing
`stereochemical_connectivity_gate` in `required_evidence`. The
`connectivity_validation` node must then register a separate
`stereochemical_connectivity_gate` evidence record with
`quality.stereochemistry_matched=true` or
`quality.stereochemical_verdict=matched`. Accepted TS audit cannot close as
supported for that hypothesis until the stereochemical gate is present and
matched.
