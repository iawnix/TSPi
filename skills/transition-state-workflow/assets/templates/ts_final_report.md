# Transition-State Search Report: {{system_id}}

## 1. Executive Verdict

| Field | Value |
| --- | --- |
| Workspace | `{{workspace_root}}` |
| Task directory | `{{task_dir}}` |
| Report generated | `{{timestamp}}` |
| Target reaction / pathway step | `{{pathway_ref}}` |
| Highest validated layer | `{{candidate | tsfreq | connectivity | accepted_ts | pathway}}` |
| Final claim | `{{accepted | not_accepted | inconclusive | needs_followup}}` |
| Accepted TS refs | `{{accepted_ts_refs}}` |
| Main evidence refs | `{{evidence_refs}}` |

**Conclusion.** {{One paragraph. State exactly what is supported, what is not
supported, and what remains open. Do not call a candidate or isolated imaginary
frequency an accepted TS.}}

**Decision for next action.** {{stop | open replacement branch | run follow-up
IRC | rerun TS/Freq | ask user}} because {{short reason}}.

## 2. Reaction Overview / Reaction And Hypothesis Scope

| Item | Value |
| --- | --- |
| Reactant endpoint | `{{reactant_ref}}` |
| Product endpoint | `{{product_ref}}` |
| Charge / multiplicity | `{{charge}} / {{multiplicity}}` |
| Atom mapping | `{{atom_mapping_ref}}` |
| Initial hypothesis | `{{hypothesis_id}}`: {{summary}} |
| Proposal source / branch anchor | `{{source_node}}` / `{{branch_anchor_node}}` |
| Proposal evidence | `{{proposal_evidence_refs}}` |
| Reaction center | {{forming bonds; breaking bonds; transferred atoms}} |
| Alternative hypotheses considered | {{list or none}} |

Endpoint provenance:

| File | Role | SHA-256 | Notes |
| --- | --- | --- | --- |
| `{{path}}` | reactant/product/mapping | `{{sha256}}` | {{source}} |

## 3. Computational Protocol

Report enough detail that the calculation can be reproduced.

| Layer | Program / version | Method settings | Key options | Artifact |
| --- | --- | --- | --- | --- |
| Candidate generation | {{backend}} | {{method}} | {{settings}} | `{{path}}` |
| TS optimization | {{program}} | {{functional/basis/model}} | {{opt keywords, convergence, constraints}} | `{{path}}` |
| Frequency | {{program}} | {{same or different method}} | {{temperature, scaling, Hessian source}} | `{{path}}` |
| IRC / connectivity | {{program}} | {{method}} | {{direction, step, max steps, endpoint opt}} | `{{path}}` |
| Rendering | `ts_render` | {{style/options}} | {{image/animation outputs}} | `{{path}}` |

Nondefault choices:

- Geometry constraints: {{none or details}}.
- Optimization convergence criteria: {{defaults or explicit values}}.
- Solvation / environment model: {{none or details}}.
- Dispersion, grid, SCF, integration, ECP, spin treatment: {{details}}.
- Remote execution: host `{{host}}`, node `{{compute_node}}`, cores
  `{{cores}}`, remote directory `{{remote_dir}}`.

## 4. R-TS-P Structural Panel

| Role | Structure | Key reaction-center distances | Rendered artifact |
| --- | --- | --- | --- |
| R | `{{reactant_xyz}}` | {{distances}} | `assets/r_ts_p_structure_panel.svg` |
| TS | `{{ts_xyz}}` | {{distances}} | `assets/r_ts_p_render.png` or missing |
| P | `{{product_xyz}}` | {{distances}} | `assets/r_ts_p_structure_panel.svg` |

## 5. Imaginary Mode / Vibration Analysis

| Field | Value |
| --- | --- |
| Imaginary frequency | {{value cm^-1}} |
| Mode-minus structure | `{{mode_minus_xyz}}` |
| Mode-plus structure | `{{mode_plus_xyz}}` |
| Mode displacement artifact | `assets/irc_key_distance_profile.svg` |
| Reaction-coordinate interpretation | {{forming/breaking/transferred coordinates}} |

## 6. IRC / Connectivity Evidence

| Direction | Endpoint artifact | Assigned basin | RMSD / metric | Key bond checks | Verdict |
| --- | --- | --- | --- | --- | --- |
| forward | `{{path}}` | reactant/product/other | {{value}} | {{values}} | {{supported/refuted}} |
| reverse | `{{path}}` | reactant/product/other | {{value}} | {{values}} | {{supported/refuted}} |

## 7. Energy Profile

Relative energies should be traceable to absolute energies and corrections in
the artifacts or appendix. If R, TS, and P are not all available at comparable
levels, report the gap explicitly.

| Species | Role | Artifact | E_elec / hartree | E+ZPE / hartree | G / hartree | Rel E_elec / kcal mol^-1 | Rel E+ZPE / kcal mol^-1 | Rel G / kcal mol^-1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R | reactant | `{{path}}` | {{E}} | {{E_ZPE}} | {{G}} | {{rel_E}} | {{rel_E_ZPE}} | {{rel_G}} |
| TS | transition state | `{{path}}` | {{E}} | {{E_ZPE}} | {{G}} | {{rel_E}} | {{rel_E_ZPE}} | {{rel_G}} |
| P | product | `{{path}}` | {{E}} | {{E_ZPE}} | {{G}} | {{rel_E}} | {{rel_E_ZPE}} | {{rel_G}} |

## 8. Mechanistic Interpretation

{{Explain how the reaction occurs. Distinguish accepted pathway evidence from
mechanistic interpretation. State whether the coordinate is tightly coupled,
asynchronous, or still compatible with a stepwise alternative. Describe which
bond changes are advanced at the TS, what the imaginary mode does, what the IRC
confirms, and which electronic-structure claims remain unproven.}}

## 9. Evidence Audit

### Candidate Generation Evidence

{{candidate evidence and rejected branches}}

### TS/Freq Validation

{{TS/Freq gate, mode assignment, convergence, frequencies}}

### Connectivity / IRC Validation

{{IRC endpoint assignment, strictness, caveats}}

### Accepted-TS Audit

{{accepted audit gates}}

### Pathway Audit

{{pathway audit outcome}}

## 10. Search Tree Summary

| Node | Node type / scope | Hypothesis ref | Program outcome | Scientific status | Key evidence | Implication |
| --- | --- | --- | --- | --- | --- | --- |
| `n000` | intake | n/a | {{program_outcome}} | {{scientific_status}} | `{{refs}}` | {{implication}} |
| `{{node_id}}` | {{node_type}} / {{scope}} | `{{hypothesis_ref}}` | {{program_outcome}} | {{scientific_status}} | `{{refs}}` | {{implication}} |

Rejected or superseded branches:

| Branch / node | Reason code | Evidence | What changed in replacement |
| --- | --- | --- | --- |
| `{{node_id}}` | {{reason_code}} | `{{evidence_refs}}` | {{changed variable}} |

## 11. Candidate Generation Evidence

Candidate-generation method:

- Input endpoints: `{{reactant_ref}}`, `{{product_ref}}`
- Generator / backend: {{QBICS, NEB, scan, conformer search, manual, other}}
- Candidate count: {{n}}
- Ranking or filter criteria: {{energy, geometry, mode expectation, distance}}
- Candidate artifact directory: `{{path}}`

Candidate table:

| Candidate | Source node | Energy / score | Key geometry | Status | Reason |
| --- | --- | --- | --- | --- | --- |
| `{{candidate_id}}` | `{{node_id}}` | {{value}} | {{key bonds}} | kept/rejected | {{reason}} |

## 12. TS/Freq Validation

| Field | Value |
| --- | --- |
| TS structure | `{{ts_xyz_or_log}}` |
| Optimization convergence | {{converged / failed / partial}} |
| Final electronic energy | {{value hartree}} |
| ZPE / thermal corrections | {{values and units}} |
| Imaginary frequency count | {{n}} |
| Imaginary frequency | {{value cm^-1}} |
| `tsfreq_gate` evidence | `{{evidence_id}}` |
| Hypothesis match | {{supported / refuted / inconclusive}} |

Imaginary-mode assignment:

| Internal coordinate | Atoms | Direction / change | Relation to hypothesis |
| --- | --- | --- | --- |
| bond | {{i-j}} | {{forming/breaking; delta}} | {{matches or not}} |
| angle/dihedral | {{i-j-k-l}} | {{delta}} | {{primary/secondary}} |

Diagnostics:

- Extra imaginary modes: {{none or list}}.
- Mode mismatch: {{none or details}}.
- Convergence warnings: {{none or details}}.
- Relevant artifacts: `{{freq_log}}`, `{{mode_animation}}`,
  `{{rendered_ts}}`.

## 13. Connectivity / IRC Validation

IRC or displacement settings:

| Field | Value |
| --- | --- |
| Starting TS | `{{ts_ref}}` |
| Direction(s) | {{forward/backward/both}} |
| Step size | {{value and units}} |
| Max steps / points | {{value}} |
| Initial Hessian source | {{calcfc/readfc/other}} |
| Endpoint optimization | {{performed / not performed}} |
| Strict IRC complete | {{yes/no; both directions normal terminated}} |
| IRC program failures | {{none or exact failure type/point}} |
| Connectivity evidence | `{{evidence_id}}` |

Endpoint assignment:

| Direction | Endpoint artifact | Assigned basin | RMSD / metric | Key bond checks | Verdict |
| --- | --- | --- | --- | --- | --- |
| forward | `{{path}}` | reactant/product/other | {{value}} | {{values}} | {{supported/refuted}} |
| reverse | `{{path}}` | reactant/product/other | {{value}} | {{values}} | {{supported/refuted}} |

Connectivity conclusion:

{{State whether forward and reverse paths connect the proposed reactant and
product basins. If both sides lead to the same basin, report the TS branch as
not accepted and identify the needed replacement hypothesis.}}

## 14. Accepted-TS Audit

Complete this section only when the accepted-audit gate is satisfied.

| Gate | Required evidence | Present | Notes |
| --- | --- | --- | --- |
| TS/Freq gate | `tsfreq_gate` | yes/no | {{evidence_id}} |
| Connectivity gate | `connectivity_gate` | yes/no | {{evidence_id}} |
| Strict IRC gate | `strict_irc_complete` | yes/no | {{forward/reverse normal termination status}} |
| Stereochemical gate | `stereochemical_connectivity_gate` if declared | yes/no/not required | {{evidence_id and verdict}} |
| Endpoint/intermediate identity gate | `endpoint_identity_gate` / `intermediate_identity_gate` if declared | yes/no/not required | {{evidence_id and boundary}} |
| Electronic/state character gate | `electronic_structure_gate` / `state_character_gate` if declared | yes/no/not required | {{evidence_id and diagnostics}} |
| Same hypothesis ID | `{{hypothesis_id}}` | yes/no | {{notes}} |
| Accepted artifact | `accepted/{{accepted_id}}.json` | yes/no | {{notes}} |

Accepted TS statement:

{{Only state accepted TS here if all required gates are yes, including the
stereochemical gate when the hypothesis declares stereochemical requirements.
Include accepted artifact path and evidence refs.}}

## 15. Pathway Audit

| Field | Value |
| --- | --- |
| Pathway ID / step | `{{pathway_id}} / {{step_id}}` |
| Audited TS refs | `{{accepted_ts_refs}}` |
| Whole R-to-P accepted | yes/no/inconclusive |
| Audit outcome | `{{accepted | pathway_not_accepted | inconclusive}}` |
| Pathway evidence | `{{evidence_refs}}` |
| Shared-basin consistency | `shared_basin_consistency_gate` if declared | yes/no/not required |

Pathway conclusion:

{{Report a negative pathway audit as a supported negative audit, not as pathway
success. State the failed branch and the next branch separately.}}

## 16. Energy Profile

Relative energies should be traceable to absolute energies and corrections in
the artifacts or appendix.

| Species | Role | Artifact | E_elec / hartree | E+ZPE / hartree | G / hartree | Rel E_elec / kcal mol^-1 | Rel E+ZPE / kcal mol^-1 | Rel G / kcal mol^-1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R | reactant | `{{path}}` | {{E}} | {{E_ZPE}} | {{G}} | {{rel_E}} | {{rel_E_ZPE}} | {{rel_G}} |
| TS | transition state | `{{path}}` | {{E}} | {{E_ZPE}} | {{G}} | {{rel_E}} | {{rel_E_ZPE}} | {{rel_G}} |
| P | product | `{{path}}` | {{E}} | {{E_ZPE}} | {{G}} | {{rel_E}} | {{rel_E_ZPE}} | {{rel_G}} |

Energy notes:

- Reference state: {{reactant complex, separated reactants, conformer, other}}.
- Corrections used: {{ZPE, H, G, single-point correction, none}}.
- Temperature / pressure: {{values}}.
- Conformer treatment: {{lowest, ensemble, not searched}}.

## 17. Figures And Rendered Artifacts

| Figure | Purpose | Artifact | Notes |
| --- | --- | --- | --- |
| Reaction panel | R / TS / P comparison | `{{path}}` | {{notes}} |
| TS mode | imaginary-mode visualization | `{{path}}` | {{notes}} |
| IRC animation | pathway inspection | `{{path}}` | {{notes}} |
| Energy diagram | barrier summary | `{{path}}` | {{notes}} |

## 18. Limitations And Open Questions

- {{Unresolved conformer issue, method uncertainty, missing IRC, ambiguous
  endpoint assignment, failed branch, spin/charge uncertainty, etc.}}
- Required follow-up: {{specific calculation or decision}}.

## 19. Artifact And Evidence Appendix

Evidence registry excerpt:

| Evidence ID | Kind | Role | Tier | Node | Path | Summary |
| --- | --- | --- | --- | --- | --- | --- |
| `{{evidence_id}}` | {{kind}} | {{role}} | {{tier}} | `{{node_id}}` | `{{path}}` | {{summary}} |

Key files:

| Path | Purpose | SHA-256 | Produced by |
| --- | --- | --- | --- |
| `{{path}}` | {{purpose}} | `{{sha256}}` | `{{node_id}}` |

Coordinates:

```xyz
{{paste short coordinate block only when useful; otherwise link artifact path}}
```

Decision JSON files:

| Node | Action | Decision file | Result |
| --- | --- | --- | --- |
| `{{node_id}}` | start/update/end | `{{path}}` | {{result}} |

## 14. Source Checklist

- [ ] Workspace validates with `python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_workspace --root {{workspace_root}}`.
- [ ] `report_workspace` was run before report generation.
- [ ] All accepted claims cite evidence IDs.
- [ ] TS/Freq, connectivity, and declared stereochemical evidence refer to the same hypothesis ID.
- [ ] Negative pathway audits are reported as negative outcomes.
- [ ] Coordinates, absolute energies, and frequency counts are present in
      artifacts or appendix.
- [ ] Rendered images/animations are labeled as visualization artifacts, not
      proof by themselves.
