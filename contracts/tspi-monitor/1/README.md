# TSPi Compute Monitor Contract

`ts-compute-monitor/1` is the durable control-plane contract between a
workspace and the Host Monitor worker. It is separate from
`ResearchMap`, `compute.run`, and the session-control transport.

The registration binds one `intent_id` and its immutable intent digest to a
workspace Node and, optionally, a Root session. A monitor tick reads the
durable Compute Attempt status and writes a deduplicated event plus a delivery
outbox record. `completed` means the program or scheduler has ended;
`parsed` is emitted only after collection and parsing have produced the bound
calculation result. `unknown` is an explicit uncertainty state.

The Monitor may wake its owning Native Pi `SessionWorker` lane and send a user
notification. It does not call `finalize`, modify `ResearchMap`, or make a
scientific decision.
Delivery uses `monitor:{event_id}` as the stable request id. A missing session
leaves the delivery pending; it is not allowed to create a new Root session.

`next_run` is the persisted wake policy name. The Monitor sends the Host an
`input/send` request in `auto` mode: the Native Worker starts a turn when the
lane is idle and queues a follow-up while it is busy. It does not use Pi's
experimental remote protocol or a second extension-owned turn queue.

Each event has a monotonic per-monitor `sequence`; returning to a previously
observed state produces a new event. Event persistence precedes its outbox and
state update, and a later tick repairs an interrupted commit. Unchanged polls
update `last_observed_at` without creating an event.

The delivery `channels.wake` and `channels.notify` have separate attempts,
claim tokens, three-minute leases, acknowledgements and exponential retry
times (5 seconds through 1 hour). Completing one channel never replays it when
the other fails. The Host and bridge deduplicate the wake business ID; the
notification receipt deduplicates the event-specific notification content.
Delivery is retryable, not a claim of exactly-once execution across arbitrary
process crashes. A disabled monitor pauses polling and outstanding deliveries.

Normal Pi stages the session/intent binding in `pending_registrations` before
submitting a calculation. A later tick can register the monitor from the
verified submission receipt or unresolved submission guard. Failed registration
is visible in status and retried without submitting the calculation again.
Automatic registrations default to `notify_policy: none`; notification delivery
requires an explicit `user` policy and configured notification transport.

The CLI exposes `list`, `status`, `enable`, and `disable` for Host/Phone clients.
Status includes observation health, delivery backlog/errors and outstanding
registration requests; workspace `worker_health.json` records polling errors.

The JSON schemas in this directory describe the persisted registration, event,
and delivery envelopes. The workspace implementation stores them below
`operations/monitors/<monitor_id>/`.

Host `monitor/event` notifications are a live projection, not a durable replay
log. Host primes its file cursor on startup, so a restart does not replay old
event files; clients recover missed state through `monitor/status` and the
durable delivery outbox.
