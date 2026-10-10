# CoRAgent Job Monitor v2

Monitor owns the durable execution wake outbox under
`operations/monitors/<monitor_id>/`. A `coragent-job-monitor/2` binding fixes the
workspace, Job, owning session, optional `user_task_id`, and optional research Node/revision at dispatch. Existing unassociated version-2 bindings omit `user_task_id`; new bindings use a task ID or null. This addition does not rewrite old immutable Job intent digests.
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
input rather than rotating its identity. A task resumed after a pre-consumption
interruption can inherit the undelivered event in its next canonical continuation;
`successor_consumption` records the consuming submission on the original provenance,
without rewriting the original Pi outcome or changing the fixed event batch.
Provider failures preserve the original
input and remain diagnosable. Monitor never marks scientific results complete.

Eligibility depends on the event, workspace/session and user-task binding, delivery
receipt, and the current task control state. It does not read Research Memory versions, Node status, checkpoints or
summaries. Closing a Node and failing a Memory projection cannot hide a Job
failure. The Job worker creates no model turn without an execution event. The
SessionWorker Task Controller can independently continue a registered active user
task through the same admission boundary, even when no Job is running.

User task pause suppresses future automatic input and consumption while observations
continue. Pending event batches keep their stable identities. The current model
request may finish; an explicit reply interruption also pauses automatic work.
An event associated with another user task cannot advance the current task.

Public TUI and Host methods are specified by the [Monitor API](../README.md).
The previous `monitor/list`, `monitor/status`, `monitor/enable`, and
`monitor/disable` RPCs are removed. Low-level Job observation and delivery
records remain internal; they are not a second user-task control API.

The event contains the submitted Node revision. The Agent can read that Node,
inspect or collect Job outputs, and publish its own research interpretation.
Actual input and output provenance remains in Job receipts and Artifact Store.

Canonical bindings omit `enabled`. Version 2 permits optional legacy
`enabled: true` only as inert metadata; it no longer controls delivery.
A stored `enabled: false` is rejected with an explicit migration error.
Resolve that persisted pause intent explicitly before upgrade recovery; never
auto-enable it or fabricate a UserTask without traceable authorization.
