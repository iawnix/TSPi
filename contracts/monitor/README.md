# Monitor API

Monitor uses the existing `coragent-host/2` RPC envelope and authentication.
`apps/agent/contracts/monitor.mjs` is the canonical method/capability list shared
by Host and browser transports. All methods are scoped to `workspace_id` and
`session_id`; there is no workspace-wide task mutation or alternate protocol.
Host forwards `{method, params}` unchanged to the owning SessionWorker's
`coragent.monitor.handle`. The Worker returns `{result, error}` internally;
Host exposes the result directly through its normal RPC result envelope.

## Requests

| Method | Additional parameters | Result |
| --- | --- | --- |
| `monitor/overview` | none | Overview |
| `monitor/tasks` | `limit?`, `cursor?` | Page of UserTask |
| `monitor/task/read` | `user_task_id` | `{task: UserTask, research: ResearchSnapshot, session_job_ids: string[]}` |
| `monitor/task/pause` | task control fields | TaskControl |
| `monitor/task/resume` | task control fields | TaskControl |
| `monitor/task/cancel` | task control fields, `jobs: "keep" \| "cancel"` | TaskControl |
| `monitor/jobs` | `user_task_id?`, `limit?`, `cursor?` | Page of Job |
| `monitor/job/read` | `job_id` | `{job: Job}` |
| `monitor/job/cancel` | `job_id`, `request_id` | `{job: Job}` |
| `monitor/runs` | `user_task_id?`, `limit?`, `cursor?` | Page of RunSummary |
| `monitor/run/read` | `run_id`, `limit?`, `cursor?` | RunDetail |
| `monitor/health` | none | Health |

Task control fields are `user_task_id`, stable `request_id`, and the current
positive `expected_revision`. Repeating the same identity and payload recovers
the Worker receipt; changing its payload is an error. A revision conflict
requires reading the task again, not silently overriding it. Cancellation must
explicitly preserve or request cancellation of owned Jobs. Cancel requests do
not prove that an external process stopped; inspect returned Job observations.

`limit` is an integer from 1 to 100. `cursor` is a nonempty opaque string from
the preceding response. Clients must not construct cursors or reuse one across
list methods. `user_task_id` names the user's work; `run_id` is Pi's first input
submission identity for that run; `pi_task_id` names an internal execution Task.
These identifiers are not interchangeable.

Removed methods `monitor/list`, `monitor/status`, `monitor/enable`, and
`monitor/disable` return `method_not_found`. CamelCase parameter aliases and
`task_id` are not accepted. The native slash parser maps user commands to this
same method set; queries never ask a model to interpret the command.

## Result shapes

The following definitions document wire projections, not new state owners.
Task state and control receipts belong to Pi durable, execution state belongs
to Pi, and Job facts belong to Job Runtime. An overview is assembled from these
sources and is not a cross-database atomic snapshot.

```ts
type Page<T> = { items: T[]; next_cursor: string | null };
type TaskState = "active" | "waiting" | "paused" | "blocked"
  | "completing" | "completed" | "cancelled";
type Criterion = { id: string; description: string };
type CompletionEvidence = { criterion_id: string; evidence_refs: string[] };
type UserTask = {
  schema_version: "coragent-user-task/2";
  user_task_id: string;
  workspace_id: string;
  session_id: string;
  conversation_id: string;
  title: string;
  objective: string;
  sources: { submission_id: string; entry_id: unknown; text: string }[];
  criteria: Criterion[];
  research: { entry_node_ids: string[]; focus_node_ids: string[] };
  state: TaskState;
  reason: string | null;
  revision: number;
  control_epoch: number;
  wait: { job_ids: string[]; mode: "all" | "any" } | null;
  progress: {
    summary: string;
    evidence_refs: string[];
    at: string;
  } | null;
  progress_version: number;
  progress_identities: string[];
  event_inputs: { submission_id: number; request_id: string; event_ids: string[] }[];
  completion: CompletionEvidence[] | null;
  completion_submission_id?: number;
  cancel_jobs?: {
    policy: "keep" | "cancel";
    pending: string[];
    receipts: Record<string, Job>;
    uncertain: string[];
    errors: Record<string, { code: string; message: string }>;
  };
  continuation: {
    sequence: number;
    reservation: {
      submission_id: number;
      request_id: string;
      control_epoch: number;
      progress_version: number;
    } | null;
    no_progress: number;
  };
  audit: { action: string; actor: string; reason: string | null; revision: number; at: string }[];
  created_at: string;
  updated_at: string;
};
type Overview = {
  schema_version: "coragent-monitor/1";
  workspace_id: string;
  session_id: string;
  task: UserTask | null;
  jobs: Page<Job> & { counts: { running: number; queued: number; total: number } };
  execution: { state: "running" | "idle"; run_id: string | null };
  task_controller: ControllerHealth;
  automatic_continuation_enabled: boolean;
  updated_at: string;
};
type TaskControl = {
  task: UserTask;
  jobs_policy: "keep" | "cancel" | null;
  job_cancellations?: Job[];
};
type RunSummary = {
  run_id: string;
  user_task_id: string | null;
  state: "queued" | "placed" | "done" | "unanswered";
  producer: "user" | "monitor" | "task_controller";
  generation_count: number;
};
type RunDetail = {
  run: { run_id: string; user_task_id: string | null };
  items: {
    pi_task_id: string;
    kind: string;
    state: string;
    outcome: string | null;
    started_at: number | null;
    ended_at: number | null;
    tool_name: string | null;
    result_entry_id: string | null;
    error: { code: string; failure_class?: string; retryable?: boolean; action_outcome?: string } | null;
  }[];
  next_cursor: string | null;
};
type ControllerHealth = {
  automatic_continuation_enabled: boolean;
  error: { code: string; message: string } | null;
  checking: boolean;
  last_checked_at: string | null;
  check_interval_ms: number;
};
type Health = {
  task_controller: ControllerHealth;
  recovery: {
    state: "recovering" | "ready" | "degraded" | "stopped";
    recovered: number;
    failures: { workspace_id: string; session_id: string; code: string; message: string }[];
  };
  host_worker_health: object | null;
  supervisor_health: object | null;
};
```

`Job` is the existing Job observation/receipt DTO returned by `job.list`,
`job.status`, and `job.cancel`, with immutable `session_id` and `user_task_id`
association on listed observations. It is not a separately maintained Monitor
Job lifecycle. Missing collection or scientific-analysis evidence must not be
presented as successful analysis merely because execution succeeded.

A session without registered tasks returns no current task. This protocol requires
UserTask v2 and Research Snapshot v3; old workspaces are not supported. Run indexes
cover execution observed by the Task Controller; runs without an index are not
invented from the active task graph. The diagnostic view presents
structured execution summaries, not model reasoning or secret tool arguments.

## Research in task details

`monitor/task/read` returns the complete UserTask plus the same bounded
`research-snapshot/3` returned by the internal `research.read` command. The
required `session_job_ids` lists snapshot Jobs also present in the session-scoped
`job.list` pages. Only those Jobs get executable `/monitor job` links. Jobs from
shared research outside the current session remain visible with an explicit
`Outside this session` label; Memory does not supply their owning session IDs.
This list is a read-time scope projection, not stored Job ownership. The
snapshot contract lives in `contracts/commands/results.json`; Monitor does not
maintain a second graph DTO. The Worker passes the task's `entry_node_ids` and
`focus_node_ids`, its session identity, and a 16,000-byte snapshot budget.
Task references are unique lists, limited to 128 entries and 16 focus nodes.
`progress_identities` accumulates stable Result identities, Artifact content
digests, and Job milestones over the task lifetime; tool output fingerprints
and combinations of evidence references are not separate progress.
They associate existing research questions with the task, without ownership,
scientific status, or execution permission.

The snapshot's `research` section contains the associated structural node cards,
relations, entry/focus references, and omission counts. Counts describe the
discovered local neighborhood; `unexpanded_nodes` identifies further branches,
not a complete graph census. Its `plan` excerpts are
not complete edit bases. Top-level snapshot nodes can provide related Result
summaries; unrelated recent context is not displayed as part of the task's graph.
Empty associations display no linked research problems. Shared problems appear
once, with edges referencing their IDs. `closed` is displayed as `Ended`, never
as successful validation; node counts are not task-completion percentages.

Terminal controls obtain the target revision from existing `monitor/tasks`
pages. They do not depend on reading the research snapshot, so unavailable
research does not prevent pause, resume, or cancellation.

Reading task details does not update the task, change its focus, submit input,
or wake a model. Research changes use the existing research tools and the single
`task_update set_research` binding action; there is no Monitor graph mutation or
new slash command. The task revision and research sequence identify separate
reads, not an atomic snapshot across Pi and Memory. Snapshot failures are surfaced
through the normal error envelope, without a second or legacy read path.

## Notifications and reconnect

A successful Monitor request subscribes that Host connection to existing
workspace Job `monitor/event` notifications. Session changes use the existing
`session/attach` and `session/event` cursor/epoch mechanism. Notifications tell
clients to refresh; they are not a second durable task-event log. After a Host
epoch change or reconnect, read a new overview and preserve focus by stable
object IDs. The browser gateway applies the same methods within its fixed,
authenticated session and requires stable mutation identity.

For execution event schemas and durable outbox semantics, see
[Job monitoring v2](2/README.md). Canonical observation bindings omit `enabled`; legacy `enabled: true` is inert
metadata. A stored false value requires explicit pause-intent migration and is
never silently resumed. Task control has only the canonical Monitor entry point.
