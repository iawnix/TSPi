# TSPi Capability-Driven Research and Node Management Plan

[English](PLAN_CAPABILITY_DRIVEN_RESEARCH.md) | [简体中文](PLAN_CAPABILITY_DRIVEN_RESEARCH.zh-CN.md)

This is the English companion to the capability-driven research plan. M0--M7
implementation work is complete within the documented first-release boundary;
the plan remains as design history and an explanation of the contracts.

## Scope

The Agent selects and composes versioned capabilities according to a scientific
question. The Kernel validates typed inputs, ownership, references, effects,
and revisions. A deterministic executor records artifacts; parsers produce
candidate observations; the Root Agent verifies and promotes evidence before
choosing the next question.

```text
question -> bounded ResearchNode -> capability run -> artifact/candidate
         -> verified Observation/Finding -> Gate/interpretation -> next Node
```

There is no fixed mechanism workflow and no automatic successor routing. A
retry that preserves the objective remains an Attempt; a changed question or
deliverable starts a new dependent Node.

## Capability Contracts

Capabilities declare a stable ID and version, input/output schemas, applicability
limits, generated files, parser candidates, and deterministic error behavior.
The registry covers reaction parsing and conservation, mapping and structure
preparation, Gaussian and IRC evidence, thermochemistry, barriers, TST,
restricted branch comparison, and chemical-network/energy-curve analysis.

Results are Node-owned, digest-bound, replayable, and promoted only through
`ts_change`. `ts_manage` pause/resume receipts are operational state and do not
add scientific lifecycle states. `ts_calc` keeps one local/remote lifecycle and
requires explicit inspection when submission or cancellation is ambiguous.

## Evidence and Release Criteria

ProofSpecs are frozen before deterministic evaluation. A successful tool call is
not a scientific conclusion; the Root Agent must inspect provenance and decide
whether to record an Observation, Finding, Claim update, or Acceptance.

The release gate covers scientific counterexamples, contract and recovery tests,
Agent integration, package inventory, wheel installation, projections, and
native App Server smoke. Real remote jobs validate software integration and
transport only; they are not universal evidence for a reaction mechanism.

Current usage and test commands are maintained in
[Scientific Capabilities: Usage and Operations](SCIENTIFIC_CAPABILITIES_OPERATIONS.md).
The design decision is [ADR 0002](adr/0002-independent-scientific-capabilities.md).
