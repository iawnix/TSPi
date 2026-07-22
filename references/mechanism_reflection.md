# Mechanism Reflection

For route-level reflection after repeated same-shape failure (wrong-basin
IRC, Gaussian route mismatch, photochemistry/open-shell/non-adiabatic), see
`references/strategy_reflection.md`.

Mechanism reasoning is hypothesis management, not a hidden state machine.

The strict workspace contract requires every search to start with a structured
mechanism hypothesis, and later nodes must reference that hypothesis by
`hypothesis_ref`. A natural-language node `hypothesis` remains useful for
display, but the authoritative mechanism object lives in
`mechanism_model.json.hypotheses[]`.

## Initial Hypothesis

The first node in a fresh workspace must be explicit `node_id=n000` with
`phase=endpoint` or `phase=preflight`. Its start decision must include
`payload.initial_mechanism_hypothesis`.

The initial hypothesis is derived from:

- reactant and product references;
- charge and multiplicity;
- atom mapping or atom-order identity;
- endpoint bond changes;
- known chemistry used as an explicitly uncertain assumption.

The hypothesis must also declare what local geometry and electronic structure
would be consistent with the proposed elementary step. Endpoint bond changes
and target distances are not enough. For the reaction center, record expected
short contacts that are allowed, short contacts that would be chemically
unwanted, key angles or coordination motifs, and the electronic diagnostics
that are meaningful for the model, such as heavy-atom charges, spin density,
orbital occupation, radical character, or excited-state population. If a
diagnostic is method- or backend-dependent, mark it as a sanity check rather
than definitive proof.

Minimum fields:

```json
{
  "hypothesis_id": "hyp_0001",
  "summary": "Concerted C-N formation on the singlet ground-state surface.",
  "derived_from": {
    "reactant_ref": "inputs/reactant.xyz",
    "product_ref": "inputs/product.xyz",
    "charge": 0,
    "multiplicity": 1,
    "atom_mapping_ref": "inputs/atom_mapping.json"
  },
  "structured_claim": {
    "reaction_center": {
      "forming_bonds": [{"atoms": [1, 2], "label": "C1-N2"}],
      "breaking_bonds": [],
      "transferred_atoms": [],
      "spectator_regions": []
    },
    "reaction_class": ["bond_formation"],
    "elementary_step_model": "concerted",
    "electronic_model": {
      "surface": "ground_state",
      "spin_surface": "singlet",
      "net_electron_transfer": "not_expected",
      "charge_transfer": "possible_but_unconfirmed",
      "spin_density_change": "not_expected",
      "pcet": "not_expected"
    },
    "pathway_ref": {"pathway_id": "p_single", "step_id": "s1"},
    "stereochemical_policy": {
      "endpoint_policy": "retain_explicit_stereocenters",
      "checks": [
        {"type": "tetrahedral", "center": 1, "neighbors": [0, 2, 3, 4], "policy": "retain"}
      ]
    }
  },
  "mechanism_claims": [
    {
      "claim_id": "claim_identity_001",
      "claim_type": "intermediate_identity",
      "subject": "post-extrusion intermediate",
      "subject_type": "intermediate",
      "summary": "The pathway uses a closed-shell singlet intermediate label, not a proven free-radical label.",
      "geometry_reflection_plan": {
        "reaction_center_metrics": ["C1-N2, C1-C3, and unintended short contacts"],
        "motif_or_coordination_checks": ["local valence and folding around the reactive center"],
        "decision_boundary": "A different local motif must be reported as a different basin label."
      },
      "electronic_structure_reflection_plan": {
        "diagnostics": ["NPA/NBO/Wiberg or method-available population analysis"],
        "decision_boundary": "Population diagnostics are method-dependent sanity checks unless the claim makes them decisive."
      },
      "state_character_reflection_plan": {
        "diagnostics": ["singlet/triplet or stable/broken-symmetry comparison when state character is claimed"],
        "decision_boundary": "Do not claim an excited/open-shell identity from geometry alone."
      },
      "required_evidence_roles": [
        "intermediate_identity_gate",
        "electronic_structure_gate",
        "state_character_gate"
      ]
    }
  ],
  "testable_predictions": [
    {
      "prediction_id": "pred_mode_001",
      "phase": "tsfreq_validation",
      "expectation": "The imaginary mode involves C1-N2 formation.",
      "required_evidence_roles": ["tsfreq_gate", "mode_assignment"]
    },
    {
      "prediction_id": "pred_mechanism_consistency_001",
      "phase": "candidate_generation",
      "expectation": "Candidate and TS/Freq summaries include local-geometry and available electronic-structure consistency checks for the declared reaction-center motif.",
      "required_evidence_roles": ["candidate_geometry", "mode_assignment"]
    }
  ],
  "required_evidence": [
    "endpoint_provenance",
    "charge_multiplicity",
    "atom_mapping",
    "reaction_center_delta",
    "initial_mechanism_hypothesis",
    "tsfreq_gate",
    "connectivity_gate",
    "stereochemical_connectivity_gate"
  ],
  "uncertainties": ["Endpoint geometry does not prove the electronic timing."],
  "alternative_hypotheses": [
    {"summary": "Stepwise C-N formation.", "changed_variable": "elementary_step_order"}
  ],
  "evidence_refs": ["ev_hyp_0001"]
}
```

## Geometry And Electronic Reflection

Every new hypothesis must split its chemistry into `mechanism_claims`. A claim
that names an endpoint/intermediate identity, electron transfer, radical or
diradical character, excited-state character, oxidation state, non-innocent
ligand behavior, carbene/nitrene/oxene identity, zwitterion, ion pair, or
shared intermediate basin must carry a geometry reflection plan and an
electronic-structure reflection plan. A state-character plan is required when
the claim depends on spin, open-shell, broken-symmetry, excited-state, or
nonadiabatic character. The validator checks that the declared evidence roles
are present before accepted/pathway audit language is allowed; it does not
hard-code chemistry-specific thresholds.

Every candidate-generation and TS/Freq reflection must explicitly answer two
questions before a candidate is promoted, a TS/Freq node is closed as supported,
or IRC is started:

- Does the current local geometry still match the declared reaction-center
  motif? Check more than target distances: nearest neighbors, unintended short
  contacts, valence or coordination changes, key angles, planarity or folding,
  spectator-region drift, and whether the geometry has fallen into a different
  local motif.
- Does the available electronic structure contradict the mechanism? Use
  diagnostics appropriate to the hypothesis, such as Mulliken/NPA/CM5 charges,
  spin density, natural orbital occupation, TD-state character, or charge
  transfer. Treat these as method-dependent sanity checks unless the hypothesis
  makes them decisive.

If either review contradicts the declared hypothesis, the node may still record
useful artifacts, but it must not label the structure as a chemically plausible
seed, must not close TS/Freq as supported, and must not start IRC from that
structure. A single imaginary frequency and a visually plausible distance
change are necessary evidence only after this mechanism-consistency review does
not refute the branch.

For multi-step pathways, endpoint assignment must be paired with identity and
shared-basin evidence when those claims are declared. `connectivity_gate` shows
where an IRC or displacement path lands; `endpoint_identity_gate`,
`intermediate_identity_gate`, `electronic_structure_gate`,
`state_character_gate`, and `shared_basin_consistency_gate` document what those
basins are allowed to be called in the mechanism.

Final reports must turn this structured mechanism state into an explicit
mechanistic interpretation section. That section should separate accepted
pathway evidence from chemical interpretation, summarize what the imaginary
mode and IRC key-distance profile imply about synchronous or asynchronous bond
changes, list alternative hypotheses that remain possible, and state which
electronic-structure or state-character diagnostics were absent. Geometry-only
connectivity must not be presented as proof of electronic timing or
intermediate identity.

Only include `stereochemical_policy` and `stereochemical_connectivity_gate`
when the reaction question depends on stereoisomer identity. Once declared,
accepted-audit closure requires a matched stereochemical connectivity gate.

`n000` may not contain TS/Freq, IRC, connectivity, or accepted-TS claims. It
only establishes whether the endpoint-derived mechanism hypothesis is usable.
When `n000` closes with `program_status=completed` and
`claim_verdict=supported`, the finalizer writes the hypothesis into
`mechanism_model.json.hypotheses[]` and sets `focus_hypothesis_id`.

## Later Nodes

All later mechanism phases must include `payload.hypothesis_ref`:

```json
{
  "hypothesis_id": "hyp_0001",
  "prediction_ids": ["pred_mode_001"]
}
```

The same reference must appear in `closure.mechanism.hypothesis_ref` when the
node is closed. This keeps candidate generation, TS/Freq validation,
connectivity validation, accepted audit, and pathway audit tied to one
mechanism chain.

## Revisions

When evidence contradicts a prediction, close the node with program facts,
scientific verdict, implication, and a mechanism revision. The finalizer updates
the referenced hypothesis but never creates a new branch automatically.

Allowed `closure.mechanism.revision.action` values:

- `refute_prediction`
- `refute_hypothesis`
- `revise_hypothesis`
- `supersede_hypothesis`

New hypotheses must be introduced by a later `start_node` decision carrying
`initial_mechanism_hypothesis` and, when replacing an unresolved branch, a
canonical `payload.branch_context` relation.

Recommended changed variables:

- `reaction_center`
- `reaction_class`
- `elementary_step_order`
- `pathway_topology`
- `proton_transfer_coupling`
- `electron_transfer`
- `spin_surface`
- `charge_state`
- `conformer_or_pose`
- `atom_mapping`
- `backend_strategy`
