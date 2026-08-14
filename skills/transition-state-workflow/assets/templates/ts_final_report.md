# Transition-State Research Report: {{system_id}}

## 1. Executive Status

| Field | Value |
| --- | --- |
| Workspace | `{{workspace_root}}` |
| Workspace revision | `{{workspace_revision}}` |
| Focus Claims | `{{focus_claim_refs}}` |
| Accepted artifacts | `{{accepted_refs_or_none}}` |
| Report generated | {{timestamp}} |

**Conclusion.** {{State exactly which Claims are supported, contradicted,
inconclusive, or accepted and what remains open.}}

**Research decision.** {{State the Root Agent's next act or explicit stop and
its cited basis.}}

## 2. Scientific Claims

| Claim | Parent | Kind | Status | Statement | Required Gates | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| `{{claim_id}}` | `{{parent_claim_id_or_none}}` | `{{claim_kind}}` | `{{claim_status}}` | {{statement}} | `{{required_gates}}` | `{{evidence_and_gate_refs}}` |

Alternative or revised Claims:

{{Describe their scientific relationship. Do not infer priority from Node
topology.}}

## 3. Computational Protocol

| Operation | Program / version | Method and settings | Inputs | Primary artifacts |
| --- | --- | --- | --- | --- |
| {{purpose}} | {{program}} | {{method_settings}} | `{{input_refs}}` | `{{artifact_refs}}` |

Record charge, multiplicity, solvation/environment, dispersion, integration
grid, SCF treatment, convergence criteria, constraints, temperature, pressure,
resources, and deviations from the intended method when relevant.

## 4. Structures And Reaction Coordinate

| Structure | Scientific use | Artifact | Key geometry | Provenance |
| --- | --- | --- | --- | --- |
| {{label}} | {{reactant / candidate / TS / endpoint / intermediate}} | `{{artifact_ref}}` | {{distances_angles_dihedrals}} | `{{evidence_ref}}` |

Imaginary-mode summary:

| Field | Value |
| --- | --- |
| Frequency | {{value_and_units}} |
| Mode assignment | {{reaction_coordinate_interpretation}} |
| Displaced structures / animation | `{{artifact_refs_or_missing}}` |
| Evidence | `{{evidence_ref}}` |

## 5. Deterministic Gate Results

| Gate result | Gate / policy | Target Claim | Verdict | Evidence | Diagnostics |
| --- | --- | --- | --- | --- | --- |
| `{{gate_result_id}}` | `{{gate}}` / `{{policy}}` | `{{target_claim_ref}}` | `{{verdict}}` | `{{evidence_refs}}` | {{diagnostics_or_none}} |

Separate at minimum:

- saddle-point/frequency facts;
- imaginary-mode assignment;
- bidirectional connectivity facts;
- any stereochemical, endpoint, electronic, robustness, thermochemistry, or
  pathway facts required by the target Claim.

## 6. Connectivity And Endpoints

| Direction | Termination | Endpoint artifact | Assigned basin | Assignment facts | Evidence |
| --- | --- | --- | --- | --- | --- |
| forward | {{status}} | `{{artifact_ref}}` | {{assignment}} | {{metrics}} | `{{evidence_ref}}` |
| reverse | {{status}} | `{{artifact_ref}}` | {{assignment}} | {{metrics}} | `{{evidence_ref}}` |

State finite-path, maximum-point, endpoint-optimization, and reference-basin
limitations explicitly. Do not describe a connection as accepted without the
corresponding passing Gate result.

## 7. Energies And Thermochemistry

Keep unlike quantities separate.

| Species | Artifact | E_elec / hartree | E+ZPE / hartree | H / hartree | G / hartree | Relative quantity / units |
| --- | --- | --- | --- | --- | --- | --- |
| {{species}} | `{{artifact_ref}}` | {{E}} | {{E_ZPE_or_missing}} | {{H_or_missing}} | {{G_or_missing}} | {{relative_value}} |

Reference state, conformer treatment, standard state, temperature, pressure,
frequency scaling, and missing corrections:

{{details}}

## 8. Research Nodes

| Node | Parent | State | Tags | Outcome | Objective | Claim / operation refs |
| --- | --- | --- | --- | --- | --- | --- |
| `{{node_id}}` | `{{parent_node_or_none}}` | `{{state}}` | {{tags}} | `{{outcome}}` | {{objective}} | `{{refs}}` |

Failed, blocked, or superseded work remains visible:

| Node / operation | Failure fact | Artifact or journal | Scientific implication |
| --- | --- | --- | --- |
| `{{ref}}` | {{fact}} | `{{source_ref}}` | {{none / explicit implication}} |

## 9. Accepted Artifacts

| Acceptance | Policy | Target Claim | Gate results | Decision | Summary |
| --- | --- | --- | --- | --- | --- |
| `{{acceptance_id}}` | `{{audit_policy}}` | `{{target_claim_ref}}` | `{{gate_result_refs}}` | `{{decision_id}}` | {{summary}} |

If no accepted artifact exists, state that directly. Normal termination, a
candidate geometry, one imaginary frequency, or advisory Review is not a
substitute.

## 10. Evidence Appendix

| Evidence | Kind / tier | Owner Node | Summary | Facts | Artifacts | Producer |
| --- | --- | --- | --- | --- | --- | --- |
| `{{evidence_id}}` | `{{kind}}` / `{{tier}}` | `{{node_id}}` | {{summary}} | `{{facts_json}}` | `{{artifact_refs}}` | {{producer}} |

List withdrawn, invalidated, and superseded Evidence separately and exclude it
from current scientific support.

## 11. Operational Follow-Up

- Unresolved compute controls: {{count_and_refs_or_none}}.
- Pending Review responses: {{count_and_refs_or_none}}.
- Missing report/render artifacts: {{list_or_none}}.
- Notification status: {{operational_status_or_not_requested}}.

Operational journals are not Evidence.

## 12. Limitations And Open Questions

- {{Scientific limitation or open question.}}
- {{Method, endpoint, conformer, spin, or sampling limitation.}}
- {{Required next discriminator, or explicit reason the study is complete.}}
