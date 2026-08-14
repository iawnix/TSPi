# @iawnix/ts-agent

`@iawnix/ts-agent` is the Pi package maintained in the TSAgentSkill repository.
It combines an evidence-driven transition-state research Skill, deterministic
workspace and compute kernels, isolated operator agents, remote SSH/Torque
execution, reporting, notifications, and a read-only workspace explorer.

This branch supports Pi Agent only. The Python entrypoints are implementation
kernels used by the Pi extensions, not a separate agent runtime.
The package supports Pi `>=0.81.1 <1.0.0` and is currently validated against
the exact Pi SDK versions in `package.json`.

## Design

The v3 architecture has one decision boundary:

```text
Root Agent chooses the research path
  -> deterministic kernel validates contracts, references, facts, Gates,
     transactions, and immutable operational bindings
```

The kernel does not choose a method, prescribe a node sequence, infer a next
step from tags, or turn a failed calculation into a scientific conclusion.

The canonical scientific model is deliberately small:

- **Node**: one bounded research act with a parent, objective, optional tags,
  references, and a terminal result. Tags are for display and search only.
- **Claim**: a versioned scientific statement selected and updated by the Root
  Agent.
- **Evidence**: immutable facts, artifact references, and provenance. Evidence
  has no workflow role or layer.
- **Gate**: a named deterministic evaluation of registered facts. Gates protect
  scientific acceptance; they do not route the workflow.

New mutations use `ts-decision/3`; nodes use `ts-node/3`. Older workspaces are
accepted only by the explicit v2-to-v3 migration command, never by runtime
compatibility aliases.

## Package Layout

- `skills/transition-state-workflow/`: the only public Pi Skill, with focused
  references and reusable decision/report assets.
- `extensions/`: deterministic workspace/infrastructure tools, isolated
  operator entrypoints, notifications, and TSPi UI.
- `src/agent-core/`: `ts-agent-task/2`, `ts-agent-result/1`, result validation,
  provider failure handling, and immutable run journals.
- `src/agents/`: private Review, compute, render, and report operator policies.
- `ts_workspace`: the only canonical scientific-state control plane.
- `ts_compute` and `ts_backends`: typed calculation intents, preparation,
  control, collection, and deterministic parsing.
- `ts_remote`: installation-owned OpenSSH/SCP and Torque lifecycle.
- `ts_render`: molecular rendering through `xyzrender` only.
- `ts_report`: atomic report-package assembly from validated v3 state.
- `ts_email`: installation-configured ClawEmail progress notifications.
- `ts_web`: read-only workspace normalization and visualization.

## Install

Create one directory per research workspace and install this development branch
project-locally:

```bash
mkdir -p /path/to/ts-workspace
cd /path/to/ts-workspace
pi install -l git:github.com/iawnix/TSAgentSkill@pi_ts_subagents --approve
export TS_WORKSPACE_ROOT=$PWD
export TS_AGENT_SKILL_ROOT=$PWD/.pi/git/github.com/iawnix/TSAgentSkill
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --workspace-root "$TS_WORKSPACE_ROOT" \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

The workspace owns its runtime manifest and default environment store:

```text
<workspace>/.agents/runtime/transition-state-workflow/env.json
<workspace>/.agents/envs/transition-state-workflow/<environment-hash>/
```

Separate workspaces therefore do not collide by default. Set the same
`TS_AGENT_ENV_ROOT` only when environment sharing is intentional.

For local package development:

```bash
cd /path/to/ts-workspace
pi install -l /absolute/path/to/TSAgentSkill --approve
TS_WORKSPACE_ROOT=$PWD npm --prefix /absolute/path/to/TSAgentSkill run install-env
```

`ts_render` uses `xyzrender` only. It does not require or probe Blender,
FFmpeg, OpenBabel, Mayavi, or PyVista; missing render support does not block
workspace validation or calculation parsing.

## TSPi

Install the package-owned `TSPi` launcher at the installation root, next to its
`.pi/`, `.agents/`, and `workspaces/` directories. Always select a workspace:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-b
./TSPi --check-remote
```

Workspace names resolve only under `<installation>/workspaces/`. Each workspace
owns its sessions, Root Agent lock, operational identity, nodes, inputs, and
reports. One nonblocking writer lock allows one Root Agent per workspace;
different workspaces can run concurrently.

Ordinary startup does not contact the cluster. `--check-remote` performs a
strict read-only SSH diagnostic and returns nonzero when the configured remote
profile is unhealthy.

The UI provides the TSPi startup header, rounded editor, stable footer, working
indicator, and a bounded `TS Activity` panel. `/ts-subagent-history` opens a
read-only paginated view of active and durable child runs. Pi's native `Ctrl+O`
expands or collapses all expandable history entries; TS entries label that
global behavior explicitly.

## Root Tools

Pi exposes eleven tools. Their prefixes describe execution authority:

- `ts_workspace_context`: read `summary`, `delta`, `node`, `lineage`, `audit`,
  `artifacts`, or adapter `capabilities`.
- `ts_workspace_decision_draft`: bind a Root-selected action and payload to the
  current report and revision without mutating state.
- `ts_workspace_decision_validate`: run schema, reference, transaction, Gate,
  and full post-mutation dry-run validation.
- `ts_workspace_decision_apply`: transactionally apply a validated decision.
- `ts_remote_inspect`: read-only `status`, `doctor`, `queues`, or `nodes`
  diagnostics for the configured SSH/Torque profile.
- `ts_subagent_review`: run an advisory Review against one target Claim and its
  deterministic dependency snapshot.
- `ts_review_disposition`: record the Root Agent's write-once response to a
  successful Review before the next scientific mutation.
- `ts_subagent_compute`: run one typed `prepare`, `submit`, `inspect`, `collect`,
  `cancel`, or `parse` operator action.
- `ts_subagent_render`: produce one node-scoped local visualization.
- `ts_subagent_report`: build one validated report package.
- `ts_notify_user`: send one deterministic installation-configured progress
  notification with bounded report attachments.

Only `ts_workspace_decision_apply` mutates canonical scientific state.
Subagent results and Review dispositions are operational records, not Evidence.

## Workspace Protocol

The Root Agent normally follows this control loop:

1. Read compact context and select one research objective.
2. Open a Node whose objective states the bounded act; tags remain descriptive.
3. Register Claims chosen by the Root Agent.
4. Link typed calculations or other immutable operation records to the Node.
5. Register parsed or observed Evidence with provenance.
6. Evaluate only the Gates required by the relevant Claim or acceptance policy.
7. Close the Node with explicit Claim updates, limitations, and optional audit.
8. Re-read context and choose the next Node, stop, or finish the study.

The four decision actions are `init_workspace`, `start_node`,
`update_workspace`, and `end_node`. The public Root tool drafts the latter
three; workspace initialization is performed by the launcher/kernel entrypoint.

Canonical files are:

```text
research_state.json
claims.json
evidence.json
gate_results.json
nodes/<node_id>/node.json
accepted/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

`report_lineage_context` is a read-only ancestry/delta query. It does not select
a checkpoint or authorize a new Node.

## Compute And Remote Execution

Preparation accepts `ts-calculation-request/1` and writes an immutable
`ts-calculation-intent/3`. The Root Agent selects the Node, scientific purpose,
backend, task, settings, resources, and attempt kind. The deterministic adapter
resolves logical `artifactId` plus `inputRole` bindings and generates paths,
filenames, expected artifacts, digests, and control identities.

The capability catalog currently expresses Gaussian `sp|opt|freq|opt_freq|irc`,
xTB `sp|opt|freq|opt_freq|scan|md`, CREST `conformer_search`, ASE `neb`, and
QBICS `dmecp`. Capability means the adapter can express and validate the task;
it does not prove local software or remote scheduler readiness.

Attempt authority lives under:

```text
nodes/<node_id>/attempts/<intent_id>/
```

`ts_remote` is the only remote subsystem. It binds an immutable submission ID
to the workspace identity, intent digest, input manifest, generated Torque
script, expected artifacts, profile, and resources. Pre-submit transfer failure
is retryable with the same binding; an ambiguous scheduler request is not.
Collection verifies declared files and hashes without depending on scheduler
history. Scheduler status is never scientific Evidence.

Remote hosts, roots, queue policy, commands, and software activation come only
from the installation TOML selected by `TS_REMOTE_CONFIG`. The Agent cannot put
transport or host configuration into a calculation request.

## Agent Protocol

Every isolated operator uses `ts-agent-task/2` and `ts-agent-result/1`. Review
receives a compact `ts-review-provider-input/2` plus a separately bound full
`ts-review-evidence-snapshot/2`; host validation checks citations against the
full snapshot. Provider failure takes precedence over output-contract failure.

Child runs are journaled under `nodes/<node>/agent-runs/<task>/` or
`operations/agent-runs/<task>/`. Journals change only the operational revision.
They do not update Claims, Evidence, Gates, or accepted artifacts.

## Notifications

Notification configuration is installation-private state. Create
`<installation>/.pi/notifications.toml` with mode `0600`:

```toml
[notifications.email]
enabled = true
recipient = "researcher@example.org"
clawemail_root = "/absolute/path/to/clawemail"
```

This fixed configuration authorizes progress delivery to one recipient. The
Root Agent supplies the event, subject, bounded summary, and optional existing
files under `reports/`; it cannot alter credentials or the recipient. Delivery
uses digest-addressed idempotency receipts. Ambiguous delivery is never retried
automatically, and notification failure does not mutate scientific state.

## Reports

Build reports only from a valid workspace:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_report.py" \
  --root "$TS_WORKSPACE_ROOT" \
  --package-dir "$TS_WORKSPACE_ROOT/reports/final_report_package"
```

Package creation is atomic and no-overwrite. `package_manifest.json` binds the
source workspace revision and every generated file by SHA-256. The standard
report projects Claims, deterministic Gate results, Evidence facts, Nodes,
accepted artifacts, open questions, and unresolved operational controls.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run test:pi-adapter
npm run typecheck
npm run test:package
npm pack --dry-run --json
```

The real-Pi integration suite uses a local recording provider to verify the
eleven-tool Root inventory, isolated child tools, Review repair semantics,
provider error propagation, lifecycle UI, and operational journals.
