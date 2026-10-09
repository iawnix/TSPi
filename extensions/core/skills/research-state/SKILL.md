---
name: research-state
description: Preserve user requirements, inspect research progress and evidence, and update the canonical TSPi research state through public tools.
---

# Research State

[中文](SKILL.zh-CN.md)

Use this Skill to preserve research obligations, evidence and decisions across
turns. Read the supplied State snapshot first; query the narrowest research_read
mode for missing or stale details. The operations mode supplies the authoritative
field schemas and examples for unfamiliar research_change operations.

- Requirement preserves a user deliverable and its minimum acceptance. Register
  it from an actual user source even if its method or template is unavailable.
  Profiles are optional check templates. Tasks may compose runtime facts,
  registered validator results and explicit Agent assessments; see
  [requirements](references/requirements.md).
- Node scopes work and dependencies. It may complete before the whole task.
  Claim records a scientific proposition; assess_claim records its evidence-based
  status. A Phase only helps navigation. Neither Claim nor Phase is mandatory
  for a simple task.
- Artifact identifies actual material, including literature and imported data.
  Attempt identifies an execution. Cite registered evidence in Findings and
  interpretations. An artifact_derive descriptor describes proposed analysis;
  run that analysis before treating its outputs as evidence.
- Gate applies reusable criteria to a particular Node or Claim. Attach one when
  the decision needs an explicit check. Every attached Gate must currently pass
  to support the corresponding completed Node or supported Claim. Ordinary Nodes
  need no Gate or exemption; closing them does not fulfil their Requirements.
- StrategyPlan records meaningful method choices and alternatives. Interpretations
  explain inspected Attempt results. They can refer to a Node without inventing
  a Claim. Routine tool observations can remain in tool history.

Mutate State through public tools, never by editing canonical files. Use
expected_revision when a stale write would be unsafe. Reference actual existing
objects. Batch errors identify operation_index and target_id; repair that target
and preserve receipts instead of repeating the external effect. Node/Claim status
changes are explicit: a Finding, Job exit, or Gate evaluation does not perform them.

Use research_checkpoint to state the disposition of the current scope before
ending. A blocked or user_input_required scope needs an explicit recovery
checkpoint before new work; a successful user_input_required checkpoint ends the
turn. Independent ready Nodes and running Attempts prevent a global user wait.
A continue_required checkpoint persists a bounded continuation for the owning
session; inspect its returned admission decision before promising another turn.

## References

- [Requirements and delivery](references/requirements.md)
- [State model](references/state_model.md) and [glossary](references/glossary.md)
- [Decision contracts](references/decision_contract.md)
- [Workspace ownership](references/workspace_contract.md)
