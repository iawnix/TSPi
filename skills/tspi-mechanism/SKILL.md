---
name: tspi-mechanism
description: Express and assess reaction mechanisms with explicit atom mappings, elementary-step findings, and capability-driven path comparisons.
---

# TSPi Mechanism

[Chinese version](SKILL.zh-CN.md)

Use this Skill for reaction definitions, atom mapping, bond changes, elementary
steps, competing pathways, or mechanism Claims. The orchestration Skill owns
the ResearchMap. This Skill chooses chemical methods and turns verified
analysis outputs into `FactFinding` or `IssueFinding` records.

## Capability Discovery

Use `ts_state mode=capabilities capabilityKind=analysis`, then query an exact
`<capability>@<version>` when input roles are unclear. Call `ts_analyze` with
role-to-Artifact-ID arrays. Read the returned artifact and diagnostics; do not
guess capability names or treat an analysis return as a Claim verdict.

## Mapping Rules

- Supply an explicit atom mapping or reuse one bound to the same input Artifacts.
- Check element labels, one-to-one coverage, total element counts, and unmapped
  atoms with the registered mapping analysis.
- Element-preserving coverage does not establish chemical identity. Resolve
  symmetry, proton transfer, fragment pairing, isotope, and electronic-state
  questions separately.
- Record verified mapping values as `FactFinding` and unresolved ambiguity or
  failed candidates as `IssueFinding`, citing source Artifact IDs.

Keep species identity, elementary-step connectivity, transition-state evidence,
thermochemistry, and kinetics as separate questions. Use independent Claims
and Claim relations for competing mechanisms. Chemical reaction networks may
contain cycles; that does not relax the acyclic ResearchNode dependency rule.

Use `ts_dispatch` only for operational pause/resume of a Node's dispatch. It does
not change the ResearchMap; use `ts_change` with `set_node_state` for scientific
state. Read [reaction mapping](references/reaction_mapping.md), [molecular preparation](references/molecular_preparation.md), [TS evidence](references/ts_evidence.md), and [energies and networks](references/energies_networks.md) for method details.
