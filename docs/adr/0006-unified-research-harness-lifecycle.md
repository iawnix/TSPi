# ADR 0006: Unified Research Harness Lifecycle and Boundaries

## Status

Accepted.

## Decision

The Root Agent makes scientific decisions. Filesystem Research State is the authority for
ResearchMap facts, evidence references, checkpoints, and liveness. Host/Harness owns input and
tool admission, permissions, workspace/session binding, recovery, and bounded follow-up.
Monitor observes external Attempts and submits operational wake inputs. Compute/Workspace
Runtime owns Attempt and Artifact execution records and never writes scientific Findings or
Claims directly. Ordinary prompts, Monitor wakes, and recovery use the Host's current Pi
submission and Worker path; Research State has no generic turn request/result protocol.

`research_checkpoint` records a durable disposition; its valid values are
`continue_required`, `waiting_external`, `deferred`, `blocked`, `terminal`, and
`user_input_required`. `continue_required` records an explicit next action. Lifecycle actions,
when used, are State records managed through `set_lifecycle_action` and
`resolve_lifecycle_action`. Liveness is a derived read model, not a second write authority.
When an active scope lacks a disposition, the Native Worker may request a bounded follow-up;
it may ask the Agent to read state and record a disposition, but may not choose a method,
Capability, Backend, Skill, parameter, or scientific conclusion.

Monitor admission calls the read-only `research.monitor_assess(event_id, session_id)` command.
Under the workspace lock, Research State checks that the event belongs to the admitted
workspace and bound session and compares it with current Attempt, Node, interpretation,
collection, and disposition state. This assessment is not an input receipt or a turn audit.
Pi submission is the durable input authority: Host stores the accepted submission there and
repeats the State assessment before first model consumption. A stale or no-longer-eligible
event is rejected before consumption.

Research Memory is durable workspace state plus bounded per-run context. Skill manifests only
enter the model-visible prompt; full skill bodies may be cached by the worker but are injected
only for explicit skill operations. Compute environments are summary first and loaded in detail
only on demand; list/show expose source and identity digests plus readiness without placing full
commands or environment variables into the default context. Public tools declare authority, effect, replay/idempotency, phase, schemas,
workspace/session binding, and error taxonomy and use the common result/error envelopes.

`research_read` (including its bounded `liveness` view) and
`research_checkpoint` are the canonical Agent/Host interfaces for research state.
`research.liveness` is diagnostic and derived; it does not persist a next step. The Native
Worker reads this same liveness projection after a run yields and may request a bounded
follow-up when an active scope has no disposition. There is no separate State turn boundary
or turn-audit store.

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
