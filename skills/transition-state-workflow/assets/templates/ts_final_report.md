# Transition-State Research Report: {{workspace_id}}

## 1. Executive Status

| Field | Value |
| --- | --- |
| Workspace | `{{workspace_root}}` |
| Scientific revision | `{{workspace_revision}}` |
| Operational revision | `{{operational_revision}}` |
| Focus Claims | `{{focus_claim_refs}}` |
| Focus ResearchActs | `{{focus_act_refs}}` |
| Current acceptance records | `{{current_acceptance_refs_or_none}}` |
| Historical acceptance records | `{{acceptance_refs_or_none}}` |
| Generated | {{timestamp}} |

**Conclusion.** {{State exactly which Claims are proposed, supported,
contradicted, inconclusive, or accepted and what remains open.}}

**Next decision.** {{State the Root Agent's next ResearchAct or explicit stop
and cite its basis.}}

## 2. Claims And Relations

| Claim | Type | Status | Statement | Assumptions | Falsifiers | Scientific basis |
| --- | --- | --- | --- | --- | --- | --- |
| `{{claim_id}}` | `{{claim_type}}` | `{{claim_status}}` | {{statement}} | {{assumptions}} | {{falsifiers}} | `{{observation_and_validation_refs}}` |

| Relation | Source | Type | Target | Rationale |
| --- | --- | --- | --- | --- |
| `{{relation_id}}` | `{{source_claim_ref}}` | `{{relation_type}}` | `{{target_claim_ref}}` | {{rationale}} |

Do not infer priority or execution order from relation labels.

## 3. ResearchAct DAG

| ResearchAct | Dependencies | Status / outcome | Objective | Hypothesis | Open questions | Derived activities |
| --- | --- | --- | --- | --- | --- | --- |
| `{{act_id}}` | `{{dependency_refs_or_none}}` | `{{status_or_outcome}}` | {{objective}} | {{hypothesis_or_none}} | {{open_questions_or_none}} | `{{activity_refs}}` |

Failed, blocked, inconclusive, stopped, merged, and backtracked work remains
visible. DAG topology records lineage and does not prescribe the next act.

## 4. Computational Protocol

| Operation | Program / version | Method and settings | Logical inputs | Primary artifacts |
| --- | --- | --- | --- | --- |
| `{{operation_ref}}` | {{program}} | {{method_settings}} | `{{input_artifact_ids}}` | `{{artifact_ids}}` |

Record charge, multiplicity/state, solvation or environment, dispersion,
integration grid, SCF treatment, convergence criteria, constraints,
temperature, pressure, resources, and deviations from intent when relevant.

## 5. Structures And Reaction Coordinate

| Structure | Scientific use | Artifact ID | Key geometry | Observation refs |
| --- | --- | --- | --- | --- |
| {{label}} | {{reactant / candidate / TS / endpoint / intermediate}} | `{{artifact_id}}` | {{distances_angles_dihedrals}} | `{{observation_refs}}` |

Imaginary-mode summary:

| Field | Value |
| --- | --- |
| Frequency | {{value_and_units}} |
| Mode assignment | {{reaction_coordinate_interpretation}} |
| Displaced structures / animation | `{{artifact_ids_or_missing}}` |
| Observations | `{{observation_refs}}` |

## 6. Semantic Observations

| Observation | Concept | Subject | Value / unit | Qualifiers | Summary | Artifact IDs | Producer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{observation_id}}` | `{{concept_id}}` | `{{subject_ref}}` | {{value}} {{unit_or_blank}} | `{{qualifiers_json}}` | {{summary}} | `{{artifact_refs}}` | {{producer}} |

Every cited artifact digest must match the recorded provenance. Do not infer
missing values or collapse unlike scientific quantities into one observation.

## 7. Frozen Validation

| GateSpec | Dimension | Target Claim | Template / registry | Checks | Digest |
| --- | --- | --- | --- | --- | --- |
| `{{spec_id}}` | `{{dimension}}` | `{{target_claim_ref}}` | `{{template_ref_or_custom}}` | {{check_summary}} | `{{spec_digest}}` |

| ValidationResult | GateSpec | Verdict | Selected Observations | Check outcomes | Digest |
| --- | --- | --- | --- | --- | --- |
| `{{result_id}}` | `{{spec_ref}}` | `{{verdict}}` | `{{observation_refs}}` | {{check_results}} | `{{result_digest}}` |

Keep `pass`, `fail`, `inconclusive`, and `error` distinct. Separate
stationary-point, reaction-coordinate, connectivity, identity, electronic,
state, robustness, thermochemical, and pathway dimensions as required by the
actual Claim.

## 8. Connectivity And Endpoints

| Direction | Program state | Endpoint artifact | Assigned basin | Assignment observations | Limitation |
| --- | --- | --- | --- | --- | --- |
| reverse | {{status}} | `{{artifact_id}}` | {{assignment}} | `{{observation_refs}}` | {{limitation_or_none}} |
| forward | {{status}} | `{{artifact_id}}` | {{assignment}} | `{{observation_refs}}` | {{limitation_or_none}} |

State finite-path, maximum-step, endpoint-optimization, atom-map, state, and
reference-basin limitations explicitly.

## 9. Energies And Thermochemistry

Keep unlike quantities separate.

| Species | Artifact ID | E_elec / hartree | E+ZPE / hartree | H / hartree | G / hartree | Relative value / units |
| --- | --- | --- | --- | --- | --- | --- |
| {{species}} | `{{artifact_id}}` | {{E}} | {{E_ZPE_or_missing}} | {{H_or_missing}} | {{G_or_missing}} | {{relative_value}} |

Reference state, conformer treatment, standard state, temperature, pressure,
frequency scaling, and missing corrections:

{{details}}

## 10. Findings And Claim Acceptance

| Finding | Severity | Status | Claims / Acts | Statement | Basis / resolution |
| --- | --- | --- | --- | --- | --- |
| `{{finding_id}}` | `{{severity}}` | `{{finding_status}}` | `{{claim_and_act_refs}}` | {{statement}} | {{basis_or_resolution}} |

| Acceptance | Claim | Profile | GateSpecs | ValidationResults | Finding snapshot | State / reason | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `{{acceptance_id}}` | `{{claim_ref}}` | `{{profile_id}}@{{profile_version}}` | `{{validation_spec_refs}}` | `{{validation_result_refs}}` | `{{finding_refs_or_none}}` | `{{current_or_historical_and_stale_reasons}}` | `{{decision_id}}` |

If no current acceptance exists, state that directly and keep any historical
record labeled stale. Claim status, program
termination, a candidate geometry, one imaginary frequency, or advisory Review
is not a substitute.

## 11. Operational Follow-Up

- Unresolved compute controls: {{count_and_refs_or_none}}.
- Activity integrity errors: {{count_and_refs_or_none}}.
- Pending Review dispositions: {{count_and_refs_or_none}}.
- Missing report/render artifacts: {{list_or_none}}.
- Notification status: {{operational_status_or_not_requested}}.

Operational journals and reports are not scientific Observations.

## 12. Limitations And Open Questions

- {{Scientific limitation or open question.}}
- {{Method, endpoint, conformer, spin/state, or sampling limitation.}}
- {{Required discriminator, counterexample search, or explicit stop reason.}}
