---
name: tspi-orchestration
description: Coordinate auditable TSPi research tasks, workspace state, decisions, evidence, validation, subagents, and operational recovery.
---

# TSPi Orchestration

[Chinese version](SKILL.zh-CN.md)

Use this Skill to organize research questions, record calculations, and verify
Claims. Represent each question as a ResearchNode and connect its results to
the workspace's scientific records. Load a domain Skill when the active question
needs method knowledge: `tspi-transition-state-search`, `tspi-xtb`, `tspi-gaussian`,
`tspi-connectivity`, `tspi-render`, `tspi-report`, or
`tspi-email`.

## Research Records

- Root chooses questions, hypotheses, methods, branches, stopping, and
  interpretation.
- The Research Kernel owns IDs, schemas, references, transactions, paths,
  provenance, gate compilation/evaluation, and validation; it does not run
  execution tools.
- Submit scientific state changes through `ts_change`.
- Use Claim relations, Node dependencies, and tags to understand prior work;
  choose the next task from the question and available evidence.
- Verify tool outputs against their artifacts before recording Observations
  or Findings.
- Use Review advice and current validation results when interpreting Claims.
  Freeze ProofSpecs before evaluating them.

## Task Loop

1. Read `frontier`, or `delta` when both prior revisions are known.
2. State one unresolved question, assumptions, predictions, and falsifiers.
3. Create or reuse a ResearchPhase and open one decision-sized ResearchNode
   with explicit dependencies, Claim scope, and an explicit completion intent;
   use a NodeGate profile when the Gate operation is available. Set focus
   deliberately.
4. Load the relevant domain Skill and select a method from the question,
   uncertainty, cost, and available artifacts.
5. Run bounded tools under the owning Node. Use logical artifact IDs and keep
   the Node open through interpretation.
6. Inspect parser candidates and primary outputs, then use `ts_change` to
   promote verified values into Observations and Findings.
7. Freeze and evaluate ProofSpecs over explicit Observation references; these
   are ClaimGate evidence dimensions. When a first-class Gate is useful, use
   `freeze_gate` and then `evaluate_gate` to persist a revision-bound result.
8. Update Claim status. For a supported Claim ready for acceptance, run
   `accept_claim`. If an explicit NodeGate exists, complete the Node only after
   its latest GateResult is `pass`; otherwise use the compatibility projection.
9. Recompile context and record the next material question as a dependent Node,
   a new Phase, or an explicit stop.

One Node is one visible question and deliverable. Retries that preserve that
question remain Attempts. A changed question, deliverable, or hypothesis scope
starts a dependent Node. Backtracking creates a new Node depending on an earlier
checkpoint and preserves all history. See
[agent_decision_protocol.md](references/agent_decision_protocol.md) for the exact Decision boundary.

## Change And Validation

Use `ts_state` for bounded reads and `ts_change` for one Root-authored atomic
change. Before an unfamiliar operation, query
`ts_state mode=change_contract operation=<op>` and follow its exact fields.
Use the IDs, paths, and receipts returned by tools; the Kernel allocates
Decision IDs when it commits the change.

Use `ts_state mode=capabilities capabilityKind=proof` for versioned ProofSpecs.
The compiler binds the template, predicate registry, content, and Observation
digests. Only `pass` satisfies a ProofSpec. Acceptance requires current passing
coverage and no applicable open blocking Finding.

## Calculations And Review

Use `mode=locate` and `mode=artifacts` before `ts_calc`; bind every input by
`artifactId` and `inputRole`. The host owns identities, paths, arguments, and
external effects. Remote `completed` still requires collection and finalize.
If a submit, cancel, or notification result is unknown, inspect its receipts
and external status before deciding how to proceed.

`ts_review` assesses one Claim dossier and a selected artifact batch in a fresh
session. Call `ts_reply` before applying advice through `ts_change`. Distinguish scheduler,
transfer, program, parser, scientific, contract, artifact, Review-provider,
and delivery failures. Preserve failed Nodes and Attempts.

## Reference Routing

Read only the contract needed for the active operation:

| Need | Reference |
| --- | --- |
| public vocabulary | [glossary.md](references/glossary.md), [glossary.zh-CN.md](references/glossary.zh-CN.md) |
| state, identity, DAG, and persistence | [state_model.md](references/state_model.md), [pathway_model.md](references/pathway_model.md), [workspace_contract.md](references/workspace_contract.md) |
| Decision fields and commit discipline | [decision_contract.md](references/decision_contract.md), [agent_decision_protocol.md](references/agent_decision_protocol.md) |
| calculation and backend executor contracts | [compute_tools.md](references/compute_tools.md), [backend_contract.md](references/backend_contract.md) |
| remote, runtime, and program failures | [remote_contract.md](references/remote_contract.md), [runtime_environment.md](references/runtime_environment.md), [program_runtime_failures.md](references/program_runtime_failures.md) |
| Review isolation and Pi context | [pi_agent_adapter.md](references/pi_agent_adapter.md) |
| structure artifacts | [artifact_tools.md](references/artifact_tools.md) |
| rendering | [render contract](../tspi-render/references/render_contract.md) |
| reports | [report template](../tspi-report/references/report_template.md) |
| notification delivery | [email delivery](../tspi-email/references/email_delivery.md) |
| authored versus installed sources | [package_sources.md](references/package_sources.md) |

Focused references live with their owning Skills. Use
`tspi-transition-state-search` for candidate strategy, `tspi-xtb` for xTB/CREST,
`tspi-gaussian` for Gaussian, and `tspi-connectivity` for endpoint and structure
evidence. Use `tspi-render`,
`tspi-report`, and `tspi-email` for visual output, report packaging, and fixed
target notification delivery.
