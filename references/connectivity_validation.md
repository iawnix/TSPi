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
