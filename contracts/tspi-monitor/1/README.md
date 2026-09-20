# TSPi Compute Monitor Contract

`ts-compute-monitor/1` is the durable control-plane contract between a
workspace and the App Server Monitor worker. It is separate from
`ResearchMap`, `ts_calc`, and the session-control transport.

The registration binds one `intent_id` and its immutable intent digest to a
workspace Node and, optionally, a Root session. A monitor tick reads the
durable Compute Attempt status and writes a deduplicated event plus a delivery
outbox record. `completed` means the program or scheduler has ended;
`parsed` is emitted only after collection and parsing have produced the bound
calculation result. `unknown` is an explicit uncertainty state.

The Monitor may queue a session `next_run` message and user notification. It
does not call `finalize`, modify `ResearchMap`, or make a scientific decision.
Delivery uses `monitor:{event_id}` as the stable request id. A missing session
leaves the delivery pending; it is not allowed to create a new Root session.

The JSON schemas in this directory describe the persisted registration, event,
and delivery envelopes. The workspace implementation stores them below
`operations/monitors/<monitor_id>/`.
