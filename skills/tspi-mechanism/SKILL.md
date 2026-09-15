---
name: tspi-mechanism
description: Express and assess reaction mechanisms with explicit atom mappings, elementary-step evidence, and capability-driven path comparisons.
---

# TSPi Mechanism

[Chinese version](SKILL.zh-CN.md)

Use this Skill when the question concerns a reaction definition, atom mapping,
bond changes, an elementary step, competing pathways, or a mechanism Claim.
Load `tspi-orchestration` for Node, artifact, Observation, and Decision
contracts. Load `tspi-connectivity` for endpoint identity and stereochemistry;
load the method Skill selected by the active capability.

Choose capabilities from the current catalog and the available evidence. The
Skill does not prescribe a calculation sequence. A mapping validation can be a
standalone Node, evidence from several Nodes can support one Claim, and a
failed candidate can remain a useful boundary.

## Capability discovery

Use `ts_state mode=capabilities capabilityKind=analysis` for the small index.
For exact input roles and parameter schemas use
`ts_state mode=capabilities capabilityKind=analysis query=<capability>@1`.
Call `ts_analyze` with `inputArtifacts` as a role-to-artifact-ID-array object,
including `{}` for reaction parsing from parameters. Outputs include an immutable
analysis artifact, generated file IDs, diagnostics, and selected fact candidates.
Read full data through the returned artifact path. Do not guess capability names.
When recording returned facts, use a `candidate_refs` entry with the existing
candidate Observation variant; it supplies value, datatype, unit and provenance.
Generated artifacts and Activities are already recorded. Promote facts when a
scientific statement needs them; input preparation alone does not require a new
Observation. Query `ts_state mode=change_contract operation=record_observation`
for either variant. In one Decision, references to newly allocated records use
`$<local_ref>`; operations such as `complete_node` refer to an existing Node and
do not allocate another local reference.

Capabilities accept independent evidence entry points. For example, an existing
Gaussian output can be analyzed without creating a ReactionSpec or mapping.

## Mapping rules

- When an analysis relies on atom correspondence, supply an explicit mapping
  or reuse an already verified one bound to the same input artifacts.
- Use `ts_state mode=capabilities capabilityKind=analysis` to inspect
  `reaction.parse`, `reaction.mapping.generate`, or `reaction.mapping.validate` and their limits.
- Use `ts_analyze` with registered reactant/product artifacts and a mapping.
  It validates element labels, one-to-one coverage, whole-reaction element
  counts, and unmapped atoms; it does not invent a map.
- Element-preserving coverage alone does not establish chemical identity.
  Resolve symmetry, proton transfer, fragment pairing, isotope and electronic
  state questions when they affect the conclusion; record unresolved evidence
  through the existing Finding contract.
- Verify the returned analysis artifact and record selected facts through
  `ts_change`; the analysis result is not a Claim verdict.

## Mechanism rules

- Keep species identity, elementary-step connectivity, TS evidence,
  thermochemistry, and kinetics as separate questions.
- Use independent Claims for competing mechanisms and ClaimRelations for
  alternatives or conflicts. Do not infer a dominant mechanism from one
  accepted TS or from a graph path alone.
- Reaction networks may contain stoichiometric multi-reactant edges,
  reversible steps, and cycles. Do not apply the acyclic ResearchNode DAG rules
  to the chemical network.
- Record conditions, standard state, charge/state, solvent/environment, and
  method for every energy or rate comparison.

Read [reaction mapping](references/reaction_mapping.md) for the current
explicit XYZ mapping contract. Read [molecular preparation](references/molecular_preparation.md)
for ReactionSpec, graph-map candidates and structure preparation;
[TS evidence](references/ts_evidence.md) for Gaussian inputs, modes and IRC;
[energies and networks](references/energies_networks.md) for thermal models,
TST, branching and chemical hyperedges. Read the pathway model and report
references through `tspi-orchestration` and `tspi-report` when producing a
multi-step conclusion.

`ts_manage operation=pause|resume nodeId=<id> rationale=<reason>` controls future
dispatch on an open Node. Existing Attempts remain inspectable, collectable and
cancellable through `ts_calc`; a terminal Node continues in a new dependent Node.
