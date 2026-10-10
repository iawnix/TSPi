# CoRAgent Job Monitor v2

Monitor owns the durable execution wake outbox under
`operations/monitors/<monitor_id>/`. A `coragent-job-monitor/2` binding fixes the
workspace, Job, owning session, and optional research Node/revision at dispatch.
Events use `coragent-job-monitor-event/2`; delivery receipts use
`coragent-job-monitor-delivery/2`. There is no version 1 adapter.

`next_run` is required on authenticated internal Monitor admission. Host and
Worker reject other modes. Admission checks Pi's active run and inbox in the
same transaction as input submission. Busy sessions keep events pending without
adding a follow-up input. Events for a session form a fixed batch before first
admission; retries reuse the same request ID and members. New events form another
batch. Claims expire after 60 seconds.

Admission, consumption, and scientific analysis are separate facts. Delivery is
acknowledged after durable model-input consumption, or when the same event was
already acknowledged. A lost response or Worker restart recovers the existing
input rather than rotating its identity. Provider failures preserve the original
input and remain diagnosable. Monitor never marks scientific results complete.

Eligibility depends only on the event, workspace/session binding and delivery
receipt. It does not read Research Memory versions, Node status, checkpoints or
summaries. Closing a Node and failing a Memory projection cannot hide a Job
failure. With no new execution event, Monitor does not create another model turn.
Host monitor/disable pauses new automatic deliveries while observations continue.
Fixed batches containing a paused event remain intact until monitor/enable.
Inputs accepted before disable keep their existing execution identity; disabling
a Monitor does not cancel an already accepted turn. Pending events remain
available for later delivery.

Host `monitor/list` and `monitor/status` return `{workspace_id, monitors}`.
Each monitor is a flat binding plus `pending_count` (undelivered events),
`last_observed_at` (latest stored execution event timestamp, or null), and
`last_error` (a pending delivery error, otherwise the latest execution error).
`last_state`, `enabled`, `session_id`, and `node_id` remain top-level fields.
These extra fields are read projections, not new persisted monitor state.
Reading them never claims, batches, or acknowledges delivery.

`monitor/enable` and `monitor/disable` return `{workspace_id, updated}`.
Clients verify that one requested monitor was updated, then use `monitor/status`
with the same `monitor_id` to obtain its current view. The mutation receipt is
not a monitor object. `updated: 0` means no matching monitor was found.

The event contains the submitted Node revision. The Agent can read that Node,
inspect or collect Job outputs, and publish its own research interpretation.
Actual input and output provenance remains in Job receipts and Artifact Store.
