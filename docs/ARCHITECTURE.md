# Research Memory architecture

This guide describes CoRAgent's current runtime and Research Memory boundaries.
See the [maintainer guide](MAINTAINER_GUIDE.md) for validation and release procedures.

## Ownership

CoRAgent uses the native Pi Harness as its only Agent loop. Workspace is the persistent research container, independent of individual sessions. Research Memory organizes original requests, local questions, repeated attempts, explicit relations and results. It does not schedule science or certify conclusions.

| Component | Owns |
| --- | --- |
| Host / Agent Server | Workspace admission, authenticated input, session binding, request identity and next_run scheduling |
| Pi session | Conversation, model requests, native tools and input consumption |
| Research Memory | Workspace storage contract, original requirements, Nodes, immutable Results and explicit research relations |
| Job Runtime | Dispatch, execution, cancellation, reconciliation and collection receipts |
| Artifact Store | Immutable file bytes and provenance manifests |
| Monitor | Execution events, outbox, delivery retry and fixed destination identity |
| Email Skill | Authorized report delivery, attachment pinning and transport receipts |
| Retrieval / Web | Rebuildable bounded views, ranking explanations and read-only navigation |

The `research_agent.research` namespace is the sole research implementation. Runtime adapters combine its data with Job and Artifact DTOs; Memory does not import execution launchers or `research_agent.application`. Shared transactions and safe file IO belong to `research_agent.foundation`. `runtime-bridge` transports commands without owning another filesystem model.

## Research model

A Node is a persistent local research question. `goal` states the question, `proposal` the current hypothesis or approach, `plan` the investigation, and `progress` the current explanation. Hypotheses are optional. Repeated parameters, geometries and failures stay within the same Node unless an independently tracked question emerges. No model-maintained Attempt entity is required.

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

Managed research Jobs explicitly bind node_id and the inspected Node revision at submission. Preparation and diagnostics can remain unassociated. Monitor events retain that original association across Node edits and session restart.

`next_run` is a real scheduling mode: persist an authenticated execution event, wait while its owning session is busy or automatic execution is paused, then submit one idempotent Pi input. Event persistence, Pi consumption and scientific interpretation are distinct facts. Lost replies reuse the same request identity; a fixed batch does not absorb later events while retrying. New notes, Node status and Memory sequence do not trigger or suppress delivery. No new event means no automatic turn merely because a Node remains open.

## Skills and delivery

Pi loads installed Skills natively. CoRAgent verifies installed resource digests. Read the actual Skill path supplied by Pi; relative references resolve from that Skill directory. `research-memory` teaches five small operations; research-workflow coordinates Jobs and materials; domain Skills teach scientific methods. `reaction_mapping.md` belongs to `chemical-input/references/`.

Process completion, file existence and Node closure do not establish a scientific result. Email uses existing user authorization and its own durable send identity. If Memory recording fails after transport acceptance, recover the record without resending. Installation, runtime and scientific claims each require their own evidence.
