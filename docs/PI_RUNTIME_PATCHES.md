# Managed Pi runtime patches

CoRAgent pins Pi v1.1.0 at `abe508e1b89912adde45528136c3221eb69acdd7`
in `config/pi-source.json`. The experimental transport protocol remains version 8.
Terminal presentation uses Pi's experimental client, separately from ordinary
`InteractiveMode`.

`scripts/prepare_pi_source.py` preflights the ordered patches in
`config/pi-patches/`, skips completely applied groups, and rejects partial or
incompatible groups before applying pending changes. Verification checks that
Git can reverse every patch; comments or version strings alone are insufficient.
A mismatched upstream commit is rejected. Keep the patch groups independent so
all pending patches can be checked before changing files.

| Patch | Purpose | Validation |
|---|---|---|
| 001-workspaces | Workspace-scoped catalog directories, metadata, cwd, and ambiguous ID rejection | Native worker startup, Host routing, existing SQLite session recovery |
| 002-worker-launch | CoRAgent worker entry and stderr diagnostics | Native worker startup and terminal diagnostics |
| 003-client-connection | Observe connection and attachment state for Unix as well as Radius | Pi client tests and native connection tests |
| 004-client-lifecycle | AbortSignal closes only the presentation; Host-selected sessions must already exist | Session switching, quit, missing-session rejection, connection disposal |
| 005-client-history | Populate input history from accepted user entries in the active transcript | Pi presentation/history tests; each session gets a new editor |
| 006-tool-presentation | Register compact tool renderers and connect Ctrl+O expansion | Native tool card rendering and retained full results |
| 007-client-status | Independent footer/activity display, expiring command feedback and dismissible documents | Native status, timer, focus, Esc interruption, resize, session-switch and disposal tests |
| 008-request-admission | Fail-closed generation hooks and one bounded compaction attempt | Request admission failure, context budget and compaction outcome tests |
| 009-input-identity | Native clients supply stable request IDs; AgentController preserves them and specific admission errors | Real native-controller and common input-admission tests |

Application integration lives outside these patches. The worker publishes the
`coragent.client-queries` service, bound to its workspace, session, kernel bridge, and
prompt manifest. The terminal consumes it through Pi's attached session service
source, including over SSH. No client-side Python process reads research state.
The slash registry is defined in `command_catalog.json`; Pi owns its editor,
selectors, transcript, model commands, and input loop.

`/resume` asks the Host for an available session in the current workspace, then
closes and recreates only the terminal presentation. `/quit` disconnects only the
terminal. SSH connections proxy both the Host and Pi sockets; proxies and their
SSH children are closed when the terminal exits.

## Updating Pi

Prepare a separate checkout under the configured test environment. Validate the
patch groups, real worker queries, presentation, session recovery, Host/Phone/
Monitor contracts, and packaging before updating the source pin and npm lock.
Source pin and Pi package versions must move together. Use a new managed runtime
directory for a new commit; existing session directories retain their layout.

Pi 1.1.0 takes the historical cutoff as `runtime.context(id, context, { at })`;
patch 008 preserves request admission on this API. The upstream context cache
uses its default idle retention (ten minutes); research snapshots are still
rebuilt for each request and are not persisted in the transcript. The estimator
now uses 3.5 characters per token, so budget admission may compact earlier.

Research tool cards show Pi's recorded `durationMs` for final results, including
after reconnect, and omit it for older or untimed results. For `job_start` this
is the tool's submission time; scientific Job duration remains owned by Job
Runtime. Expanded cards preserve the full result and label the tool duration.

Pi 1.0.3 renamed the Azure provider from `azure-openai-responses` to `azure`.
Installations using Azure must update that provider key in authentication, model,
and settings configuration when moving from 1.0.2 to 1.0.4. The corresponding
`AZURE_OPENAI_*` environment variables are unchanged. This upgrade does not add
ordinary Pi's full command set to the experimental TUI.

Monitor admission is implemented in CoRAgent's worker service rather than another
Pi source patch. `monitor-admission.mjs` uses the pinned
`packages/durable/src/harness/submissions.ts` transaction primitive
`admitSubmission`: run/inbox checks, immutable input provenance and placement
share one short Pi commit. All State/Python assessment runs outside that commit.
The Worker reassesses internal input before its first model consumption and
records the State basis against the submission, across generation task changes.
An authenticated producer submits structured event IDs; message text and ID
prefixes never establish provenance. Monitor acknowledges consumption, retaining
pending or deferred events and earlier identities when State supersedes an input.
Native tests cover busy rejection, batch idempotency, a slow bridge racing native
input, consumption reassessment, and real Worker/Host restart recovery. Recheck
the internal Pi API on every pin update.

The CoRAgent footer shows model, thinking level, workspace/session, estimated context
and cumulative model tokens. `/usage` opens provider-reported input/output/cache
counters; reasoning is not added again to output. `pi.usage` preserves totals
across compaction. The worker telemetry query uses Pi's internal
`harness/compaction.ts:estimateContext` with the conversation's canonical context
and the selected model's configured capacity. Recheck that estimate API when
updating Pi; it is not a tokenizer or a billing measurement. Changed context or
model identity invalidates an old estimate until refreshed. Set `CORAGENT_TUI_RING=0`
for a numeric-only context display on fonts without suitable circle glyphs.

The presentation subscribes to Host Monitor events and refreshes read-only
snapshots on reconnect and every five seconds. Monitor status includes an
observational pending-delivery summary; reading it never claims or batches an
outbox entry. Counts are scoped to the attached session, while worker health is
shared. Host `next_run` is not a Pi inbox enum: accepted queued messages use
`followUp`. User input retains Pi's own queue display. Monitor waits
for idle admission, so busy-session wakes normally remain pending delivery.
