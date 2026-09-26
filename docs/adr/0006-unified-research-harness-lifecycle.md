# ADR 0006: Unified Research Harness Lifecycle and Boundaries

## Status

Accepted.

## Decision

TSPi uses one domain-neutral Research Turn boundary for ordinary prompts, Monitor wakes,
recovery, and retries. The Agent is the only scientific decision-maker. Research Kernel is
the only scientific state authority. Host/Harness owns lifecycle, permissions, workspace and
session binding, tool contracts, recovery, and bounded follow-up. Monitor only observes external
Attempts and queues operational wakes. Compute/Workspace Runtime owns Attempt and Artifact
execution records and never writes scientific Findings or Claims directly.

The Kernel command `research.turn` uses `research-turn-request/1` and
`research-turn-result/1` for `start`, `orient`, `checkpoint`, `end`, and `wake`. It records
operational turn audit under `operations/research_turns.jsonl`; these events are not ResearchMap
facts. A supplied `request_id` is an idempotency key: an exact retry is marked `replayed` and
does not append another audit event; reusing that key with a different operation, turn, session,
trigger, or delivery identity is rejected as a command error.

`research_checkpoint` is the only turn-closing boundary. Its valid dispositions are
`continue_required`, `waiting_external`, `deferred`, `blocked`, `terminal`, and
`user_input_required`. `continue_required` means the Agent has recorded an explicit
next-turn action. The old `required` value is accepted only when reading or migrating
the compatibility `research_continuation` ledger and is normalized to
`continue_required`; it is not a second lifecycle state.
Monitor records `research.turn(operation=wake)` before acknowledging a wake delivery; a failed
boundary leaves the delivery pending for retry. `decision_needed` is the only state that requires a bounded Host follow-up. Host follow-up may
ask the Agent to read bounded state and record a disposition, but may not choose a method,
Capability, Backend, Skill, parameter, or scientific conclusion.

Research Memory is durable workspace state plus bounded per-turn context. Skill manifests only
enter the model-visible prompt; full skill bodies may be cached by the worker but are injected
only for explicit skill operations. Compute environments are summary first and loaded in detail
only on demand; list/show expose source and identity digests plus readiness without placing full
commands or environment variables into the default context. Public tools declare authority, effect, replay/idempotency, phase, schemas,
workspace/session binding, and error taxonomy and use the common result/error envelopes.

`research_read` (including its bounded `liveness` view) and
`research_checkpoint` are the canonical Agent/Host interfaces for a turn.
`research.liveness` is diagnostic only; it does not persist a next step.
`research_continuation` remains a compatibility interface for reading or
migrating older required-action records. `research.turn` remains the lifecycle
boundary that interprets these records. The Native Worker's `before_run_end`
boundary invokes the same lifecycle evaluation and must not implement a second
liveness or continuation state machine.

Runtime enforcement is centralized at tool admission. Every production tool must expose
`label`, `description`, a parameter schema, an executable `execute` function, and the exact
four-field Harness metadata contract. Public tool names must match the canonical metadata
registry; unknown metadata values, fields, or public-tool drift are rejected before a Worker
is created. Result adapters also reject malformed content and persist a
`tool_contract_violation` error instead of passing an invalid value into Pi Core.

Tool errors use one bounded failure taxonomy: `validation`, `authorization`, `workspace`,
`conflict`, `ambiguous`, `transient`, `execution`, or `contract`. Explicit `retry_safe` marks
eligible execution failures retryable, while transient failures are retryable by default;
validation, authorization, workspace, conflict, ambiguous, and contract failures are never
silently replayed.

At invocation time, the Harness passes a Host-created branded `ToolExecutionContext` containing
the bound workspace root, session identity, operation identity, lifecycle phase, replay mode, and
allowed authority/effect/phase policy. The wrapper binds the context to the current invocation
before calling the implementation and rejects missing or forged context, phase/authority/effect
mismatches, workspace or session conflicts, missing operation identity, and non-replayable tools
during recovery. The Agent may supply ordinary tool arguments only; it cannot declare or widen
this execution context.

The native Worker supplies this context through a private synchronous lifecycle provider. The
`before_drive` boundary provisionally marks an operation as recovery; `before_run` replaces it
with a normal or Monitor-wake turn when a new prompt is admitted. `before_tool` admits only the
next phase in the Host-owned phase graph, and `after_tool` advances the graph after a successful
tool result. The provider is refreshed at invocation time, so multiple tool batches in one run
observe the current phase while Agent arguments cannot alter the policy. A cold-resumed operation
therefore permits safe/idempotent reconciliation but rejects `replay: never` effects before their
implementation is entered.
