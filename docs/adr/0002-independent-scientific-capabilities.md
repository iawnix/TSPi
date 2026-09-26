# Independent scientific analysis and Node dispatch management

[English](0002-independent-scientific-capabilities.md) | [简体中文](0002-independent-scientific-capabilities.zh-CN.md)

Status: implemented within the documented first-release scope (2026-09-16).
Use the focused scientific-analysis, package, and component test suites as the
current validation record. One-off validation reports are intentionally not
checked into `docs/`.

## Context

Mechanism research needs reaction identities, atom correspondence, TS/path
evidence, thermal models and selected-network comparison without prescribing a
fixed sequence. Fine-grained ResearchNodes remain valuable for scientific
records, recovery and direct user intervention. Adding a separate lifecycle
for every species or tool result would increase maintenance without evidence.

## Decision

Use one versioned `analysis_run` envelope with an on-demand capability catalog.
New domain schemas stay outside the always-loaded tool definitions. Dispatch
is an explicit ID/version lookup; descriptors never select a next capability.
Existing `compute_run`, structure comparison and rendering implementations remain
the execution authorities for their respective domains.

Pure analysis handlers consume bounded artifact snapshots and explicit
parameters. The engine writes content-addressed Node-owned outputs plus a
`ts-scientific-analysis/1` document binding request, sources, digests, results
and generated files. Domain results distinguish valid, invalid, inconclusive
and unsupported; successful execution never means scientific acceptance.

Analysis outputs are transient parser candidates in Node-owned artifacts. The
existing `research_change` operation creates a selected `FactFinding` or
`IssueFinding` only after replaying its registered handler and checking
input/output bindings. Analysis never fabricates a calculation intent.
Candidate replay assumes the installed capability version's deterministic
algorithm; algorithm changes require a new capability version.

`execution_dispatch` is a small operational pause/resume interface. Its Node-scoped
receipt chain is outside canonical science. A shared workspace lock orders
pause against analysis and the durable submission-guard claim. Operations
already past that boundary are in flight; pause does not promise cancellation.
Inspect, collect, parse and exact-Attempt cancellation remain available.
Resuming a terminal Node is rejected; subsequent research uses a dependency.
The tool is explicit because `research_read` is read-only and `research_change` is the
scientific transaction API. No new scientific Node status was introduced.

Reports and Web consume the canonical ResearchMap serialization. A chemical network contains
stoichiometric hyperedges and may contain cycles; the ResearchNode DAG retains
its original provenance meaning and acyclicity.

## Consequences and limits

The public surface adds 891 UTF-8 bytes for analysis and 466 for Node management
under the existing byte-measurement fixture. The original tool budget is still
13,000 bytes; new tools have separate 900/500-byte caps. This is a static proxy,
not evidence of a 25% reduction in actual model tokens.

The first implementation supports closed molecular chemistry and explicit
ideal-gas thermal corrections with declared solution/electronic conditions.
Graph mapping is bounded and can remain ambiguous. Mode overlap is a selected
bond-derivative diagnostic. Elementary TST and initial irreversible branching
are not general microkinetics. Candidate networks express their selected scope;
they never claim exhaustive discovery.

No automatic asynchronous chemistry workflow is introduced. The conditional
Host convenience layer in M1 remains gated on measured operational burden.
