# Transition-State Workflow Native Pi Subagent Plan

Status: scientific subagent MVP and no-submit compute-operator MVP implemented
and locally validated. Authorized submit/cancel, direct GitHub-install, and
broader release probes remain deferred.

Target branch: `feat/native-pi-subagent`

Target source tree:
`/home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor`

## 1. Decision Summary

Develop the subagent capability inside this package. Do not depend on an
external `pi-subagents` package and do not add a non-standard `pi.subagents`
manifest field.

The package will expose two deliberately different execution planes:

1. `ts_workspace_subagent`: a fresh, read-only scientific review session built
   with the Pi SDK.
2. `ts_workspace_compute_operator`: a fresh operational session backed by
   request-scoped typed calculation and job-lifecycle tools.

The current compute operator exposes dry-run prepare, inspect, collect, and
parse only. Submit and cancel remain absent until separate host-created
authorization capabilities and real probe tests are implemented.

The root Pi agent remains the only scientific decision authority and the only
caller allowed to mutate canonical TS workspace state.

## 2. Why the Previous Design Changes

Pi 0.81.1 package discovery supports extensions, skills, prompts, and themes.
It does not natively discover package agents through `pi.subagents`. The prior
plan therefore depended on an external package contract that is not part of the
current package surface.

Seven independent agents plus seven private skills would also create excessive
prompt surface, duplicated policy, and an implicit phase pipeline. This is at
odds with the branch's hypothesis-driven, non-linear research model.

The replacement design uses one subagent runtime with a small enum of review
modes. Review modes select compact prompt modules; they do not create separate
authorities, sessions with inherited history, or globally discoverable skills.

## 3. Goals

- Reduce root-agent context pressure at difficult scientific decision points.
- Give independent reviews a fresh context window.
- Preserve candidate, TS/Freq, connectivity, accepted-audit, and pathway-audit
  evidence boundaries.
- Reuse `report_workspace`, `report_node`, and `report_branch_context` as the
  only workspace context sources.
- Keep subagent output advisory, structured, bounded, and source-referenced.
- Prevent subagents from mutating workspace state or recursively delegating.
- Separate scientific review permissions from calculation-operation
  permissions.
- Support Pi project-local package installation and GitHub package installation
  without source-checkout-relative execution assumptions.

## 4. Non-goals

- Do not create a fixed candidate -> TS/Freq -> connectivity pipeline.
- Do not create one agent per backend, phase, or decision template.
- Do not let an LLM output become primary scientific evidence.
- Do not let a subagent write `research_state.json`, `hypotheses.json`, or
  `evidence_registry.json`.
- Do not expose generic `bash`, `write`, `edit`, or recursive subagent tools.
- Do not keep an LLM session alive while a long Gaussian or cluster job runs.
- Do not submit, cancel, delete, or alter remote jobs in the first
  implementation.
- Do not synchronize, commit, push, or deploy as part of implementation unless
  separately authorized.

## 5. Authority Model

### 5.1 Root Pi agent

The root agent owns:

- the scientific question and evidence layer under investigation;
- hypothesis, pathway, branch, parent, anchor, and solution selection;
- calculation intent and method selection;
- workspace mutation decisions;
- acceptance, stopping, escalation, and user-facing conclusions;
- reconciliation of conflicting subagent advice;
- all calls to mutation tools.

### 5.2 Scientific review subagent

The scientific subagent may:

- inspect one bounded task packet;
- challenge a hypothesis or interpretation;
- identify conflicts, missing evidence, or alternative tests;
- compare a failure trigger with a selected historical checkpoint;
- return structured observations and decision options.

It must not:

- read arbitrary workspace files;
- mutate files or workspace state;
- submit or alter calculations;
- promote a candidate to TS/Freq, connectivity, accepted TS, or accepted
  pathway beyond the selected review layer;
- emit an authoritative workspace verdict;
- delegate recursively.

### 5.3 Compute operator

The compute operator may perform only explicitly exposed operational
actions. It cannot select a mechanism, close a node, set `claim_verdict`, or
interpret program completion as scientific support.

Backend adapters and parsers remain deterministic code. The compute operator is
a constrained coordinator around those mechanisms, not a replacement for them.

## 6. Architecture

```text
root Pi agent
  -> ts_workspace_context / report APIs
  -> select one review question
  -> ts_workspace_subagent
       -> validate request
       -> build bounded task packet
       -> create fresh in-memory Pi AgentSession
       -> load replacement system prompt only
       -> expose no tools in MVP
       -> request structured advisory JSON
       -> validate output and evidence references
       -> return compact advice + run metadata
  -> root reconciles advice with primary evidence
  -> root optionally calls ts_workspace_decision_validate
  -> root optionally calls ts_workspace_decision

root Pi agent
  -> create explicit calculation intent
  -> ts_workspace_compute_operator
       -> validate one operation request
       -> create fresh in-memory Pi AgentSession
       -> bind only request-scoped typed compute tools
       -> expose no general filesystem, shell, mutation, submit, or cancel tool
       -> validate report fields against actual tool results
       -> return operational report + deterministic action results
  -> root verifies primary artifacts and decides whether to register evidence
```

The subagent is a real Pi `AgentSession`, but it does not inherit the parent
conversation. The implementation reuses Pi's provider and authentication
runtime while owning its context, prompt, tool, timeout, and output contracts.

## 7. Proposed Layout

```text
transition-state-workflow/
├── SKILL.md
├── package.json
├── extensions/
│   ├── shared/
│   │   └── workspace-cli.ts
│   ├── ts-workflow-context/
│   │   ├── index.ts
│   │   └── summary.cjs
│   ├── ts-workflow-subagent/
│   │   └── index.ts
│   └── ts-workflow-compute/
│       └── index.ts
├── compute-agent/
│   ├── runtime.ts
│   ├── prompt.md
│   └── output-schema.cjs
├── ts_compute/
│   ├── control.py
│   ├── cli.py
│   └── contracts/
├── subagents/
│   ├── runtime.ts
│   ├── session-lifecycle.cjs
│   ├── task-packet.cjs
│   ├── output-schema.cjs
│   └── prompts/
│       ├── core.md
│       ├── mechanism.md
│       ├── candidate.md
│       ├── tsfreq.md
│       ├── connectivity.md
│       ├── final-audit.md
│       └── program-failure.md
└── tests/
```

`subagents/` contains implementation modules and prompt data, not discoverable
Pi skills. Existing detailed scientific rules stay under `references/` as the
single source of truth.

## 8. Pi Package Integration

Register the new extension through the standard package manifest:

```json
{
  "pi": {
    "skills": ["."],
    "extensions": [
      "./extensions/ts-workflow-context",
      "./extensions/ts-workflow-subagent/index.ts",
      "./extensions/ts-workflow-compute/index.ts"
    ]
  }
}
```

Do not add `pi.subagents`. Do not add role prompts or `subagents/` to
top-level `pi.skills` or `pi.prompts`.

The extension must derive package paths from `import.meta.url`. It must not
assume the package is a copied skill tree or that Pi's current working directory
is the package root.

## 9. Scientific Subagent Tool

Register one root-visible tool:

```text
ts_workspace_subagent
```

### 9.1 Request contract

```json
{
  "reviewType": "connectivity",
  "question": "Are the available endpoint assignments sufficient?",
  "root": "/path/to/workspace",
  "nodeId": "n012",
  "fromNode": "n014",
  "anchorNode": "n012",
  "evidenceRefs": ["ev_..."],
  "artifactRefs": ["nodes/n012/outputs/result.json"]
}
```

Rules:

- `reviewType` is one of `mechanism`, `candidate`, `tsfreq`, `connectivity`,
  `final_audit`, or `program_failure`.
- `question` is required and size-limited.
- `nodeId` selects a historical-node context capsule.
- `fromNode` and `anchorNode` must appear together and must pass existing branch
  topology validation.
- Evidence references must exist in the report-derived scope.
- Artifact references must be reachable through report-derived artifact refs;
  arbitrary paths are rejected.
- Model, thinking level, timeout, and tool selection are host policy, not
  model-controlled request fields.

### 9.2 Invocation policy

Use the subagent only at high-value decision boundaries:

- competing mechanism hypotheses;
- a refuted branch requiring backtrack or replacement selection;
- ambiguous TS/Freq or connectivity interpretation;
- conflicting evidence;
- program failure whose technical and scientific meanings may be confused;
- accepted-TS or pathway-audit preflight.

Do not invoke it for every node, every tool result, or every turn. Do not encode
review modes as a mandatory sequence.

### 9.3 Review-mode evidence ceilings

| Review type | May assess | Must not claim |
|---|---|---|
| `mechanism` | Hypothesis consistency, alternatives, discriminating tests | Candidate quality, TS/Freq support, connectivity, acceptance |
| `candidate` | Candidate/search quality and candidate-level evidence | TS/Freq support, connectivity, accepted TS/pathway |
| `tsfreq` | Optimization/frequency/parser facts and mode assignment | R/P connectivity, accepted TS/pathway |
| `connectivity` | Displacement, endpoint assignment, basin, IRC, stereo gates | Accepted TS/pathway without the separate audits |
| `final_audit` | Missing prerequisites and consistency of accepted/pathway audit inputs | Authoritative acceptance or pathway-success verdict |
| `program_failure` | Technical failure class, provenance, bounded repair options | Any scientific claim as evaluated or supported |

The selected review type fixes the output ceiling. The child model cannot raise
that ceiling in its response.

## 10. Task Packet

The extension, not the root model, builds the final child prompt. A task packet
contains only:

- packet schema version and run ID;
- workspace root and current report ID;
- selected review type and scientific question;
- compact workspace summary;
- selected node capsule when requested;
- selected backtrack comparison when requested;
- active hypothesis/pathway identifiers;
- allowlisted evidence summaries;
- allowlisted parsed facts or bounded artifact excerpts;
- role-specific evidence ceiling;
- explicit `authority=advisory` statement;
- required output schema.

Default limits:

- at most 4 artifact excerpts;
- at most 16 KiB per artifact excerpt;
- at most 64 KiB of artifact text in one packet;
- at most 96 KiB total serialized packet size;
- text files only in the first implementation;
- no raw trajectory, checkpoint, binary, image, or unrestricted log injection.

Large Gaussian logs must be reduced by deterministic parsers or bounded tail /
selected-section extraction before inclusion.

## 11. Pi SDK Isolation

Each call creates a new session with:

- `SessionManager.inMemory(workspaceRoot)`;
- in-memory settings with compaction disabled for the bounded call;
- a resource loader with no extensions, skills, prompts, themes, or context
  files;
- a replacement system prompt assembled from `core.md` plus one review module;
- `noTools: "all"` in the MVP;
- the parent-selected model only when it is available in the child
  `ModelRuntime`;
- the parent thinking level clamped by Pi;
- one active invocation at a time initially;
- a host-owned timeout, initially 90 seconds and capped at 180 seconds;
- abort propagation from the parent tool call;
- unconditional session disposal in `finally`.

Do not silently fall back to a different model. Return a visible error when the
parent model/provider cannot be recreated by the child runtime.

## 12. Advisory Output Contract

```json
{
  "schema_version": "ts-subagent-advice/1",
  "authority": "advisory",
  "review_type": "connectivity",
  "scope": {
    "report_id": "rep_...",
    "node_ids": ["n012"],
    "hypothesis_id": "hyp_...",
    "pathway_id": null
  },
  "findings": [
    {
      "layer": "connectivity",
      "statement": "...",
      "status": "uncertain",
      "basis_refs": ["ev_..."]
    }
  ],
  "missing_evidence": [],
  "conflicts": [],
  "options": [
    {
      "action": "...",
      "discriminator": "...",
      "risks": []
    }
  ],
  "limitations": []
}
```

Validation rules:

- reject malformed or non-JSON output;
- reject unknown fields through `additionalProperties: false`;
- require `authority=advisory`;
- require returned scope IDs to match the task packet;
- require every `basis_ref` to belong to the packet allowlist;
- enforce a review-type-specific maximum evidence layer;
- reject unknown or authoritative fields such as `accepted_ts=true` and
  pathway-success fields;
- keep the child tool-free so text in advisory `options` cannot execute a
  mutation or job action;
- cap model-visible output at 16 KiB;
- return schema failures as tool errors, never as partial scientific advice.

Natural-language claims cannot be made safe by keyword scanning alone. The root
skill must still state that subagent output is analysis, not evidence, and must
reconcile it against primary artifacts and registered evidence.

## 13. Session Metadata and Context Hygiene

After a valid run, the extension may append a lightweight parent-session entry:

```text
customType: ts-workspace-subagent-run
data: run_id, review_type, report_id, node_ids, output_digest,
      schema_valid, model, usage, duration
```

Do not store full artifact excerpts, prompts, credentials, or private logs in
the custom entry. `appendEntry` metadata is for Pi session audit and is not a
canonical workspace state file or scientific evidence.

Subagent advice is not automatically injected into future turns. The tool
result remains in the parent conversation; a later session must reconstruct
scientific context from workspace reports, not stale subagent prose.

## 14. Parent Decision Tool Boundary

Separate read-only decision preflight from mutation:

```text
ts_workspace_decision_validate  # validate only
ts_workspace_decision           # mutations only
```

`validate_decision` is removed from the mutation tool's action enum. In the MVP,
the scientific subagent receives neither decision files nor preflight output;
the root agent reconciles advisory findings, then calls the read-only preflight
tool itself before any mutation.

## 15. Compute Operator Design

### 15.1 Why it is separate

Scientific review and calculation operation require incompatible permissions.
The review subagent is context-rich and tool-free. The compute operator is
chemistry-blind and tool-constrained. Combining them would let scientific
reasoning directly cause remote side effects.

### 15.2 Existing foundation

- `ts_backends` prepares calculation inputs and parses result facts.
- `ts_remote.job_lifecycle` stages, submits, polls, tails, fetches, kills, and
  records receipts.
- Backend and remote contracts already prohibit workspace verdicts.

The implemented no-submit layer provides typed tools with workspace path
validation, backend/host allowlists, fixed timeouts, idempotent intent
preparation, and compact job status returns. Submit/cancel capability gates are
still intentionally absent.

### 15.3 Calculation intent

The root agent creates an explicit intent before operational work:

```json
{
  "schema_version": "ts-calculation-intent/1",
  "intent_id": "calc_...",
  "node_id": "n012",
  "purpose": "test pred_mode_001",
  "evidence_layer": "tsfreq",
  "backend": "gaussian",
  "task_type": "opt_freq",
  "input_refs": {"gjf": "nodes/n012/inputs/candidate.gjf"},
  "settings": {},
  "expected_artifacts": [],
  "execution_target": {"kind": "local"},
  "dry_run": true
}
```

The root owns method and scientific-purpose selection. The operator may report
an incompatible or incomplete intent, but it cannot silently replace the
method, task type, or evidence target.

### 15.4 Typed operational tools

Read/preparation surface:

```text
ts_workspace_compute_prepare
ts_workspace_compute_status
ts_workspace_compute_tail
ts_workspace_compute_collect
ts_workspace_compute_parse
```

External side-effect surface:

```text
ts_workspace_compute_submit
ts_workspace_compute_cancel
```

Keep submit and cancel as separate tool names. An action enum would prevent the
host from allowing status while denying submission.

| Tool | Primary effect | Default availability | Authorization |
|---|---|---|---|
| `prepare` | Write validated node-scoped input artifacts | Compute operator | Existing running node and valid intent |
| `status` | Read remote/process status | Compute operator | Read-only remote access |
| `tail` | Read a bounded remote artifact tail | Compute operator | Read-only remote access |
| `collect` | Fetch allowlisted artifacts into node outputs | Compute operator | Valid receipt and destination policy |
| `parse` | Produce deterministic parser facts | Compute operator | Collected allowlisted artifact |
| `submit` | Stage and launch external work | Not present by default | Explicit current authorization/capability |
| `cancel` | Terminate external work | Not present by default | Separate explicit authorization/capability |

Operational tools must:

- reject arbitrary shell commands;
- derive commands from backend adapters;
- require an existing node and write only under its `inputs`, `outputs`,
  `remote`, or `scratch` directories;
- validate local and remote paths;
- enforce backend, login-host, compute-host, and environment allowlists;
- default to dry-run;
- use duplicate-submission protection and stable intent/job IDs;
- record node-scoped receipts and provenance;
- return program status and parser facts, not scientific verdicts.

### 15.5 Authorization

Each compute-operator session contains only the tools required by its selected
operation: one tool for prepare, collect, or parse; status plus optional tail
for inspect.

Submit or cancel tools may be injected into one compute session only after a
current-turn user authorization or a separately documented fixed policy. The
authorization capability is created by host code and is never accepted as a
model-provided string field.

Cancel, delete, overwrite, and resubmit are distinct actions. Authorization for
one does not imply authorization for another.

### 15.6 Calculation result

```json
{
  "schema_version": "ts-calculation-result/1",
  "job_id": "job_...",
  "intent_id": "calc_...",
  "node_id": "n012",
  "state": "completed",
  "program_status": "completed",
  "exit_status": 0,
  "artifact_refs": [],
  "parser_facts": {},
  "error_class": null,
  "provenance": {}
}
```

The result schema must not contain `claim_verdict`, accepted-TS state,
connectivity support, or pathway conclusions.

### 15.7 Long-running job return

Do not keep a compute-agent LLM session alive while a job runs.

1. Prepare and optional submit return an intent/receipt and terminate.
2. A deterministic watcher or explicit status call updates node-scoped remote
   status.
3. State changes produce compact job deltas.
4. Only changed or terminal job deltas may be injected once into a parent Pi
   session; unchanged jobs are not re-injected every turn.
5. Terminal jobs are collected and parsed deterministically.
6. The root agent decides whether parser facts justify `update_workspace`,
   `end_node`, retry, branch replacement, escalation, or user input.

Job receipts under `nodes/<node>/remote/` remain the durable source. Any global
active-job index is derived runtime state, not a fourth canonical research state
file.

### 15.8 Program failures

The compute layer may classify technical failures such as input syntax,
environment, resource, SCF, optimizer, termination, staging, or scheduler
errors. It may propose a bounded repair for root review.

It must distinguish technical failure from scientific failure:

- program failure -> `program_status=failed`, scientific claim not evaluated;
- wrong imaginary mode -> TS/Freq-layer scientific issue;
- same-basin displacement -> connectivity-layer issue;
- missing strict R/P proof -> accepted/pathway audit blocker.

No automatic Gaussian repair may resubmit without a new or explicitly approved
intent.

## 16. Implementation Phases

### Phase A: Native scientific subagent contracts - complete

1. Add request, packet, output, and role-layer schemas.
2. Add prompt modules with one shared authority contract.
3. Add tests for packet scope, evidence allowlists, output validation, and size
   limits.
4. Do not change root behavior yet.

### Phase B: Pi SDK runtime and tool - complete

1. Implement the fully isolated in-memory AgentSession runtime.
2. Register `ts_workspace_subagent` through a new package extension.
3. Add timeout, abort, model-resolution, usage, and disposal handling.
4. Add lightweight session metadata after valid runs.
5. Keep the child tool-free.

### Phase C: Root orchestration and decision preflight - complete

1. Add concise delegation triggers and reconciliation rules to `SKILL.md`.
2. Add `ts_workspace_decision_validate`.
3. Restrict `ts_workspace_decision` to mutation actions.
4. Verify fallback behavior when the child model is unavailable or output is
   invalid.

### Phase D: Typed compute tools, dry-run first - complete

1. Wrap existing backend prepare/parse and remote status/collect functions.
2. Enforce node-scoped paths, allowlists, timeouts, and typed results.
3. Expose prepare/status/tail/collect/parse only.
4. Test with synthetic workspaces and local dry-runs; do not submit jobs.

### Phase E: Compute operator - MVP complete

1. Create a separate isolated operator runtime with only typed compute tools.
2. Add calculation-intent and result validation.
3. Keep durable status node-scoped and inject no automatic all-turn job summary.
4. Validate basic remote and Gaussian program-failure classes against
   deterministic status/parser facts.

### Phase F: Authorized external side effects - deferred

1. Add submit only after explicit authorization tests pass.
2. Validate real receipt, duplicate prevention, poll, collect, and parser flow on
   an approved synthetic/probe job.
3. Add cancel last with separate authorization and audit tests.
4. Do not add automatic resubmission.

Parallel review, chains, multiple specialist agents, and automatic calculation
repair remain out of scope until the single-agent paths are stable and measured.

## 17. Validation Plan

### 17.1 Static and unit validation

- package manifest contains no `pi.subagents` dependency or field;
- `subagents/` prompts are not globally discovered as skills/prompts;
- all schemas reject unknown fields;
- task packet evidence and artifact refs are workspace-derived;
- path traversal and out-of-node paths fail;
- packet and output size limits are enforced;
- review modes enforce their maximum evidence layers;
- malformed, authoritative, or cross-layer child output fails visibly;
- child active-tool list is empty in MVP;
- no recursive subagent or mutation tool is discoverable;
- sessions dispose after success, error, abort, and timeout.

### 17.2 Pi integration validation

- project-local package reference loads all three extensions;
- GitHub/git-installed package resolves prompts and package root correctly;
- a synthetic workspace supports workspace, node, and backtrack review calls;
- the child context contains only the replacement prompt and task packet;
- unrelated global/project skills, context files, and extensions are absent;
- parent and child model resolution failures are explicit;
- parent receives schema-valid advice and run metadata;
- root does not treat advice as evidence or automatically mutate the workspace.

### 17.3 Compute validation

- prepare writes only under the selected node;
- backend commands cannot be supplied as arbitrary strings;
- status/tail/collect/parse work without submit permission;
- submit and cancel are absent by default;
- model-supplied fake authorization cannot enable side-effect tools;
- duplicate submission is rejected;
- watcher/status changes produce one compact delta per change;
- unchanged jobs produce no repeated context injection;
- parser facts never set scientific verdict fields;
- Gaussian technical failure remains distinct from TS/Freq or connectivity
  failure.

### 17.4 Repository validation

- focused Pi adapter/subagent tests;
- full `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -q`;
- Node/TypeScript extension syntax or type validation available in the package;
- skill validation;
- `npm pack --dry-run --json` with inspection of the extension, runtime, schema,
  and prompt file list;
- real Pi JSON-mode smoke tests against a synthetic workspace;
- source/install diff review before any synchronization.

No validation step may submit or cancel a remote job without separate current
authorization.

## 18. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Subagent becomes a second scientific authority | Fixed advisory schema, evidence ceilings, root-only mutations and conclusions |
| Context split hides governing evidence | Extension-built packet from report APIs, role ceiling, explicit missing-evidence output |
| Prompt modules duplicate references | Keep prompts procedural and compact; existing references remain authoritative |
| Global Pi context leaks into child | Empty resource loader, in-memory session, replacement prompt, context-isolation tests |
| Model returns invented evidence refs | Packet allowlist and output subset validation |
| Child silently uses another model | Explicit model resolution failure; no fallback |
| Subagent is called every turn | Root delegation policy limits calls to ambiguity and audit boundaries |
| Compute operator gains scientific authority | Calculation intent/result schemas contain no scientific verdict fields |
| Scientific reviewer gains operational authority | Separate runtimes and disjoint tool registries |
| Model invents authorization | Host-created ephemeral capabilities; no authorization string parameter |
| Long jobs bloat context | Durable receipts plus changed/terminal deltas only |
| Gaussian repair loops consume resources | No automatic resubmit; each changed intent requires root review and authorization |

## 19. Definition of Done: Scientific Subagent MVP

- The package contains no external subagent dependency.
- `ts_workspace_subagent` is loaded through standard Pi package extension
  discovery.
- Exactly one native subagent runtime supports the six review modes.
- Every call uses a fresh in-memory context with no inherited skills,
  extensions, context files, parent history, or tools.
- Task packets are report-derived, path-bounded, and size-bounded.
- Output is schema-valid, advisory, evidence-referenced, and layer-bounded.
- Invalid output fails visibly and cannot be mistaken for advice.
- Root remains the only workspace mutator and scientific authority.
- No automatic delegation, chain, parallel mode, or recursive delegation exists.
- Focused tests, full pytest, package dry-run, skill validation, and real Pi
  synthetic-workspace smoke tests pass.

## 20. Definition of Done: Compute Operator

The no-submit MVP satisfies the typed-tool, path, schema, isolation, and
program/science separation requirements below. The full definition remains
open until Phase F adds separately authorized submit/cancel capabilities and an
approved end-to-end remote probe.

- Existing backend and remote mechanisms are exposed only through typed tools.
- Prepare/status/tail/collect/parse are path-restricted and dry-run-safe.
- Submit and cancel are separate, absent by default, and must become
  capability-gated before either is implemented.
- Calculation intent and result schemas preserve program/science separation.
- Long jobs return through receipts and changed/terminal deltas, not persistent
  LLM waits or all-turn summaries.
- No tool can write canonical workspace state or set a scientific verdict.
- Approved end-to-end probe validation covers prepare, submit, poll, collect,
  parse, and root-agent interpretation without automatic acceptance.

## 21. Release Boundary

Implementation and validation occur source-first on
`feat/native-pi-subagent`, branched from
`refactor/consolidate-research-state`.

Commit, push, synchronization into any installed skill tree, real remote job
submission, and deployment are separate actions requiring explicit user
authorization and a final source/install diff review.
