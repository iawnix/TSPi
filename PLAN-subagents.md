# Isolated Agent Architecture

Status: node ontology, four-tool context/control plane, generic agent protocol,
scientific review, backend compute, render, report, and email-draft operators
are implemented. Email sending remains unavailable pending a host-issued,
current-turn authorization capability.

Foundation branch: `refactor/research-node-ontology`
Artifact branch: `feat/pi-artifact-operators`

## Authority Model

### Root Agent

The Root Agent alone owns:

- hypothesis proposal, comparison, revision, and falsification;
- prediction and validation-scope selection;
- candidate, branch, parent, anchor, and pathway selection;
- method and calculation-intent selection;
- evidence registration and workspace decisions;
- audit status, study completion, stopping, and user-facing conclusions;
- reconciliation of conflicting child results.

### Child Agents

Every child is a fresh Pi `AgentSession`. It receives no parent conversation,
context files, root skills, root extensions, `AGENTS.md`, or general tools.
Children share a workspace path only as a bounded artifact namespace; they do
not share model context or canonical write authority.

Roles:

| Role | Authority | Current execution surface |
|---|---|---|
| `review` | advisory | tool-free bounded scientific review |
| `backend` | operational | typed `prepare|inspect|collect|parse` tools |
| `render` | operational | typed node-scoped local render |
| `report` | operational | typed validated report-package build |
| `email` | operational | typed local draft only; sending unavailable |

No child may set hypothesis status, choose a branch, accept a TS/pathway, mark
the study complete, or mutate canonical state.

## Research Tree

New nodes use:

- `intake`
- `mechanism`
- `candidate_search`
- `validation`
- `audit`

This is not a fixed phase pipeline. The Root Agent may open any scientifically
valid next node supported by current evidence and topology.

Examples:

- wavefunction analysis: `validation/electronic_structure`, followed by a
  `mechanism/evaluate` node;
- one-frequency calculation: `validation/tsfreq`;
- displacement or IRC endpoint assignment: `validation/connectivity`;
- method sensitivity: another validation node with
  `attempt_kind=recalculation` and `relation=recalculation_of`;
- pathway completion: `audit/pathway` or `audit/study`.

## Four Workspace Tools

```text
ts_workspace_context
ts_workspace_decide
ts_workspace_validate
ts_workspace_apply
```

Responsibilities:

1. `context`: read `summary|delta|node|branch|audit` context.
2. `decide`: bind the Root Agent's action/payload to current report and
   revision without mutation.
3. `validate`: enforce schema, evidence refs, node topology, authority, and
   stale-revision rules.
4. `apply`: invoke one matching mutation transaction and return refreshed
   context.

The tools do not choose research direction. `ts_workspace_apply` is the only
canonical mutator.

## Context Policy

Do not inject the full workspace tree every turn.

At turn start, Pi injects only a short reminder that a TS workspace is active
and names the control plane. The Root Agent pulls context based on need:

- summary at decision boundaries;
- delta after a known revision;
- one node when a historical checkpoint may matter;
- branch context before backtracking;
- audit context before acceptance or stopping.

Canonical files are not inserted independently:

| Information | Context source |
|---|---|
| current node, focus, frontiers, status axes | `report_workspace` summary |
| one historical closure and artifacts | `report_node` capsule |
| trigger, anchor, intervening attempts | `report_branch_context` capsule |
| hypothesis predictions and status | report-derived hypothesis context |
| evidence details | selected node/branch evidence allowlist |
| tree topology | compact report index, expanded only for selected lineage |

The child receives neither decision files nor preflight output. It receives a
bounded task packet built by the extension.

## Communication Protocol

All children use `ts-agent-task/1` and `ts-agent-result/1`.

Task fields:

```json
{
  "schema_version": "ts-agent-task/1",
  "task_id": "agent_...",
  "role": "backend",
  "authority": "operational",
  "operation": "parse",
  "objective": "Parse the bound local Gaussian artifact.",
  "workspace": {
    "root": "/path/to/workspace",
    "report_id": "rep_...",
    "revision": "sha256:..."
  },
  "scope": {
    "report_id": "rep_...",
    "node_ids": ["n012"],
    "hypothesis_id": "hyp_001",
    "pathway_id": null
  },
  "inputs": {},
  "capabilities": ["ts_workspace_compute_parse"],
  "constraints": {
    "canonical_workspace_mutation": false,
    "scientific_decision": false,
    "recursive_delegation": false,
    "remote_authority": "execution_mirror",
    "external_side_effects": false
  },
  "output_contract": "ts-agent-result/1"
}
```

Result fields:

```json
{
  "schema_version": "ts-agent-result/1",
  "task_id": "agent_...",
  "role": "backend",
  "authority": "operational",
  "operation": "parse",
  "outcome": "success",
  "summary": "The bound artifact was parsed.",
  "scope": {},
  "facts": [],
  "artifact_refs": [],
  "program": {
    "outcome": "success",
    "state": "parsed",
    "error_class": null,
    "exit_status": 0
  },
  "payload": {},
  "limitations": [],
  "provenance": {}
}
```

The host validates identity, role, authority, operation, scope, facts, artifact
refs, and role-specific payload. It recursively rejects authoritative fields
such as:

- `hypothesis_status`
- `branch_context`
- `claim_verdict`
- `accepted_ts`
- `pathway_accepted`
- `strict_pathway_decision`
- `study_complete`

## Scientific Review

`ts_workspace_subagent` review modes:

- `mechanism`
- `candidate`
- `tsfreq`
- `connectivity`
- `final_audit`
- `program_failure`

Each mode fixes an evidence ceiling. Findings must cite evidence or artifact
refs in the task allowlist. Uncited gaps belong in `missing_evidence`.

Use review only when an independent pass could change a Root Agent decision:
competing hypotheses, conflicting evidence, ambiguous validation, program
failure analysis, backtrack selection, or final audit. Do not invoke after
every node or tool result.

## Backend Operator

The Root Agent first writes a `ts-calculation-intent/2` and passes the selected
backend to `ts_workspace_compute_operator`.

The child receives one private backend skill:

- `backend-gaussian`
- `backend-ase`
- `backend-xtb`
- `backend-qbics`

`backend-rdkit` is defined but not activated until a typed adapter exists.

The child receives only the typed tools needed for the requested operation.
Output is checked against actual tool results. Backend completion remains a
program outcome, never scientific support.

## Attempt And Remote Model

New operational records live under:

```text
nodes/<node>/attempts/<intent>/
```

Technical retries stay under the same research node. Scientifically meaningful
recalculations open a new research node and cite the source node/intent.

Remote work directories declare `authority=execution_mirror`. Collection into
the local attempt directory and local verification are required before evidence
registration.

An LLM session does not stay alive while a Gaussian or cluster job runs.
Durable status files and `ts_web` carry monitoring state.

## Render, Report, And Email Operators

Private skills and request-scoped adapters enforce these role boundaries:

- render: allowlisted local molecular input to declared visual artifact;
- report: validated read model to report package without new claims;
- email: local draft from a generated report summary and explicit recipients;
  no sending, network, sender selection, or credentials.

Each role receives exactly one typed child tool. Paths reject traversal,
symlinks, and overwrite. Role-specific validators bind every returned artifact,
node, recipient, and subject to the typed action result. Generic shell,
filesystem, network, and canonical workspace tools remain unavailable.

Email sending is a separate milestone. It requires a host-issued capability
bound to exact recipients, current-turn authorization, and the selected draft
digest; model-supplied authorization fields are never sufficient.

## Validation Matrix

- protocol schema and recursive authority rejection;
- fresh-session resource isolation;
- review evidence-ceiling and basis allowlist;
- backend tool/result binding;
- one selected private backend skill per session;
- one selected artifact skill and typed tool per render/report/email-draft
  session;
- traversal, symlink, overwrite, recipient-change, and invented-artifact
  rejection;
- abort, timeout, and unconditional disposal;
- v2 attempt paths and remote mirror label;
- report and `ts_web` separation of program, hypothesis, and audit status;
- Pi package inventory and real tool smoke.
