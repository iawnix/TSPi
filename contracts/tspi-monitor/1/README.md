# TSPi Job Monitor

The current Job runtime stores `ts-job-monitor/1` bindings and
`ts-job-monitor-event/1` events in `operations/monitors/<monitor_id>/`.
Each binding names a workspace, Node, Job, Attempt and owning session. Monitor
polls execution status and writes terminal or queue-wait events to a durable
wake outbox. It never sends email or changes scientific conclusions.

Pending events for the same session are assigned an immutable batch request ID
before delivery. A retry reuses the same membership and message. Previously
attempted deliveries retain their original request ID. Claims have a 60-second
lease; an offline worker or uncertain response leaves the delivery pending.

`next_run` is the current transport mode. Monitor input is
admitted through the worker's `tspi.monitor-admission` service, which checks
Pi's run and inbox in the same transaction that submits the input. A busy
session leaves events in the outbox, without adding follow-up prompts. The
transaction deduplicates committed submissions by request ID, including after
an uncertain Host response or restart.

Research State reassesses durable event identities immediately before admission.
A matching observed Attempt is obsolete once it has an interpretation, or its
outputs have been collected and its Node is closed. Workspace termination alone
does not suppress an unhandled failure. Blocked, deferred and user-input waits
retain events for a later State revision/checkpoint. Obsolete events are
acknowledged without a model request. The worker withdraws obsolete legacy
Monitor follow-ups on startup and at tool/yield boundaries; ordinary user input
and unhandled events remain intact.

Successful scheduler exit is not scientific validation. The Agent still needs
to collect outputs, inspect evidence and record the appropriate Research State
decision. Status, binding and outbox files remain available for diagnosis.

The JSON schemas in this directory describe the current Job binding, event and
`ts-job-monitor-delivery/1` outbox. Host scans `binding.json` under
`monitor_<digest>/`, with `event_<digest>` identities and exact `job_id`,
`attempt_id`, and `job_digest` agreement. Old compute envelopes, `registration.json`,
`calc_*`, `intent_id`, and `intent_digest` are not accepted or converted.
