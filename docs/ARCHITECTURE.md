# Research Memory architecture

This guide describes CoRAgent's current runtime and Research Memory boundaries.
See the [maintainer guide](MAINTAINER_GUIDE.md) for validation and release procedures.

## Ownership

CoRAgent uses the native Pi Harness as its only Agent loop. Workspace is the persistent research container, independent of individual sessions. Research Memory organizes original requests, local questions, repeated attempts, explicit relations and results. It does not schedule science or certify conclusions.

| Component | Owns |
| --- | --- |
| Agent Server / Host | Service hosting; Host owns workspace admission, authentication, session routing and worker recovery discovery |
| Pi SessionWorker / durable Harness | Sole owner of session storage, conversation, model/tool execution, atomic input admission and recovery |
| Research Memory | Workspace storage contract, original requirements, Nodes, immutable Results and explicit research relations |
| Job Runtime | Dispatch, execution, cancellation, reconciliation and collection receipts |
| Artifact Store | Immutable file bytes and provenance manifests |
| Monitor / Task Controller | User task intent and continuation policy in the SessionWorker; Job monitoring observes execution and delivers events |
| Email Skill | Authorized report delivery, attachment pinning and transport receipts |
| Retrieval / Web | Rebuildable bounded views, ranking explanations and read-only navigation |

The `research_agent.research` namespace is the sole research implementation. Runtime adapters combine its data with Job and Artifact DTOs; Memory does not import execution launchers or `research_agent.application`. Shared transactions and safe file IO belong to `research_agent.foundation`. `runtime-bridge` transports commands without owning another filesystem model.

## Research model

A Node is a persistent local research question. `goal` states the question, `proposal` the current hypothesis or approach, `plan` the investigation, and `progress` the current explanation. Hypotheses are optional. Repeated parameters, geometries and failures stay within the same Node unless an independently tracked question emerges. No model-maintained Attempt entity is required.

Compound studies use independently interpretable questions and existing `part_of`, `requires` and `alternative_to` relations. A root Node is optional; shared questions can have multiple parents. UserTask `/2` stores only `research.entry_node_ids` and `research.focus_node_ids`, set together through `task_update` action `set_research`. These are navigation references, not ownership, a schedule or a second plan. Node and Result schemas remain unchanged.

Node status is `open`, `paused` or `closed`. Closing means stopping active work on that question; it does not imply scientific success or cancel a Job. The authored revision changes when Node content changes, independently of background execution observations. Concurrent content changes require a new reading and explicit merge; append-only notes do not replace another author's judgment.

A Result fixes a useful observation and conclusion, limitations, actual input versions, evidence and files. It is immutable and may be negative or inconclusive. Explicit `supersedes` preserves the old version. A Node's selected assessment is a deliberate synthesis, not simply its latest result or latest Job failure. Upstream correction creates an exact review notice; it never silently replaces downstream inputs or reruns science.

## Relations and provenance

`part_of`, `requires` and `alternative_to` are explicit Agent declarations stored once. Reverse links and map indexes are generated. Containment cannot cycle; competing approaches and research feedback do not require the whole map to be a DAG. Circular current waits are diagnostics, not tool admission failures.

Actual `uses` and `cites` connections require recorded material inputs or explicit result references. Similar filenames, equal bytes, browsing and search are not evidence that a particular scientific source was adopted. Each Result retains concrete earlier versions, so feedback in the research map does not create circular evidence. Untracked input provenance remains untracked.

## Model-facing interface

| Tool | Minimum request |
| --- | --- |
| research_read | `{}` for a bounded context, or `{ref}` for an exact object |
| research_search | `{query}` |
| research_create | `{goal}` |
| research_update | `{node_id, note}` |
| research_result | `{node_id, conclusion}` |

Updates may change proposal, plan, progress, status or assessment and add/withdraw explicit relations. Result files refer to registered Artifacts. Session, workspace, request identity, read basis and revisions are supplied by the trusted adapter. Models do not maintain transaction metadata, reverse edges or a global progress object. There is no lifecycle checkpoint or yield-repair prompt.

## Workspace and storage

`workspace_manifest.json` uses `research_workspace/2`. Research records preserve original user messages and distinct author/runtime origins. Stable Node directories under `research/nodes/<id>/` contain their current view and work files; immutable results and history preserve earlier versions. Research indexes, reverse links and generated Markdown are rebuildable. Titles and relationship changes do not move directories.

`runs/jobs/` owns execution working directories. `operations/` owns durable intents, observations, collection/delivery receipts and exact short references. `artifacts/<id>/payload` and `manifest.json` own fixed file versions. Mutable Node work files must be registered before a Result cites them as published material. Reports remain ordinary user-facing files with fixed delivered versions.

Transactions publish coherent research updates and recover interrupted commits. Old graph and notebook workspaces are rejected without migration or mutation. Create a new workspace and explicitly import useful materials; no dual reader or compatibility writer is supported.

## Context and next_run

A bounded model context preserves original user intent and the authenticated trigger, then ranks relevant Nodes using event association, explicit focus, pending execution facts and research relations. Necessary result summaries and direct dependencies accompany selected Nodes. Omission has explicit read/search routes; retrieval never presents missing content as completed work. Ordinary user text cannot impersonate Monitor metadata.

Before every model request, `GenerationTask.beforeRequest` reads the current Task and passes its complete entry/focus references to the internal Memory reader. The single `research-snapshot/3` projection reserves space for the study structure and local plan excerpts before admitting execution facts and detailed Node cards. It shows a bounded containment neighborhood and direct focus relations, including shared parents. Truncated fields do not grant replacement read receipts. Monitor task details use this same projection; browsing does not write focus or wake the model.

Managed research Jobs explicitly bind node_id and the inspected Node revision at submission. The trusted tool adapter also binds the current `user_task_id`; this is separate from scientific Node ownership. Preparation and diagnostics can remain unassociated. Monitor events retain the original associations across Node edits and session restart.

`next_run` is a real scheduling mode: persist an authenticated execution event, wait while its owning session is busy or automatic execution is paused, then submit one idempotent Pi input. Event persistence, Pi consumption and scientific interpretation are distinct facts. Lost replies reuse the same request identity; a fixed batch does not absorb later events while retrying. New notes, Node status and Memory sequence do not trigger or suppress delivery. An open Node does not create an automatic turn. A separately registered active user task can continue without a new Job event.

## Persistent user tasks and Monitor

The request-only task projection bounds serialized bytes and explicitly points omitted original requirements, criteria and evidence to `task_read`; truncation never relaxes authorization. A user task spans Pi runs and compute Jobs. `task_begin`, `task_read` and `task_update` record the authorized objective, cited user submissions, delivery criteria, progress evidence and explicit waits or blockers. Ordinary questions do not create tasks. A session has at most one nonterminal user task. Its control state lives only in Pi durable documents; Host does not store a duplicate task lifecycle or control receipt.

The Task Controller runs inside the SessionWorker. Normal tools continue within the native Pi loop. After a completed run, a durable `task_controller` input can continue an active idle task through the same admission transaction used by other inputs. The implementation does not install an `onYield` continuation path. Watch notifications and a 30-second check reconcile outstanding work; Job waits query concrete owned Jobs and invoke no model until ready. Three automatic runs without new evidence block further continuation with an explanation. A normal answer ending is not user-task completion: proposed completion needs evidence for every criterion and a successfully delivered final response.

Pause suppresses new automatic work while the current response and Jobs can finish. Interrupting a response also pauses the user task. Resume is a user control operation. Cancellation requires an explicit keep/cancel policy for owned Jobs. Querying Monitor does not send a prompt or resume a task. `CORAGENT_AUTOMATIC_CONTINUATION=0` disables automatic input while preserving user input and read access.

Progress observations and explicit progress updates share persistent identities: individual Result IDs, Artifact content digests and owned Job milestones. Plan edits, notes, Node creation and focus changes are activity without progress credit. Reusing an identity, changing a reference combination or restarting does not replenish the allowance. Each completion criterion needs fixed Result or Artifact evidence; scientific applicability remains the Agent's responsibility. These controls cannot assess whether newly produced evidence is scientifically valuable.

Host restart discovers sessions from Pi's existing catalog and reopens at most four Workers concurrently; each Worker reconciles its durable task. Recovery failures appear in `monitor/health`. No process besides the SessionWorker writes its SQLite store. The aggregate is a projection of independent Task, Pi and Job owners, not a cross-system atomic snapshot.

`/monitor` is the unified product entry point for tasks, Jobs and execution details. Host and browser transports share one canonical method list in `apps/agent/contracts/monitor.mjs`; the [Monitor contract](../contracts/monitor/README.md) describes requests and results. Pi generation/tool Tasks appear under a run's diagnostic details, never as user tasks. Existing session and Job notifications request a fresh snapshot after changes or reconnects.

## Skills and delivery

Pi loads installed Skills natively. CoRAgent verifies installed resource digests. Read the actual Skill path supplied by Pi; relative references resolve from that Skill directory. `research-memory` teaches five small operations; research-workflow coordinates Jobs and materials; domain Skills teach scientific methods. `reaction_mapping.md` belongs to `chemical-input/references/`.

Process completion, file existence and Node closure do not establish a scientific result. Email uses existing user authorization and its own durable send identity. If Memory recording fails after transport acceptance, recover the record without resending. Installation, runtime and scientific claims each require their own evidence.
