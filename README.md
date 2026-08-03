# TSAgentSkill

TSAgentSkill is an evidence- and hypothesis-driven transition-state research
workflow for Pi Agent. It separates scientific decisions, program
execution, evidence registration, branch topology, reporting, and read-only
visualization.

This branch supports Pi Agent only. The Python packages and command-line
entrypoints are implementation kernels used by the Pi extensions, not a
separately supported agent runtime.

New work uses `ts-decision/2` and `ts-node/2`. Legacy phase-based workspaces
remain readable and closable, but they are not the model for new studies.

## Architecture

- `ts_workspace`: the only canonical research-state control plane.
- `ts_compute` and `ts_backends`: typed calculation intents, preparation,
  host-authorized submission/cancellation, status, collection, and
  deterministic parsing.
- `cluster_mcp` and `ts_remote.mcp`: authenticated, manifest-bound file
  transfer and OpenPBS/Torque execution without scientific authority.
- `subagents/`: fresh Pi review sessions and the shared
  `ts-agent-task/1` / `ts-agent-result/1` protocol.
- `artifact-agent/`: fresh render, report, and email-draft sessions with
  request-scoped typed tools and role-specific result binding.
- `agent-skills/`: private backend, render, report, and email skills. They are
  not registered in the Root Agent's Pi skill inventory.
- `ts_render`: local molecular rendering through `xyzrender` only.
- `ts_report`: report-package assembly from validated workspace evidence.
- `ts_web`: read-only workspace normalization and visualization.

The Root Agent is the sole authority for hypothesis status, branch selection,
audit conclusions, stopping, and workspace decisions. A completed calculation
is only a program fact.

## Install

Create the research workspace, install this branch project-locally through Pi,
then create a workspace-owned runtime from the Pi-managed checkout:

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

The default runtime manifest is:

```text
<workspace>/.agents/runtime/transition-state-workflow/env.json
```

The default Conda prefix store is:

```text
<workspace>/.agents/envs/transition-state-workflow/<environment-hash>/
```

Therefore separate Pi research workspaces do not collide by default. Set the
same `TS_AGENT_ENV_ROOT` only when deliberate environment sharing is wanted.
The package checkout, including a Pi `.pi/git/...` checkout installed directly
from GitHub, never owns the workspace runtime when `--workspace-root` is used.

From the package checkout:

```bash
TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env
TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env:core
```

## Render Dependency Boundary

`ts_render` uses `xyzrender` only.

It does not require or probe Blender, FFmpeg, OpenBabel, Mayavi, or PyVista.
Missing render support does not block workspace validation or calculation
parsing.

## Pi Agent Usage

The native adapters support Pi `>=0.81.1 <1.0.0` with matching Pi SDK packages
and are currently validated against Pi `0.83.0`. Pi
project-local installation registers a package reference; it does not copy the
skill into a requested directory.

Local package reference:

```bash
cd /path/to/ts-workspace
pi install -l /absolute/path/to/TSAgentSkill --approve
```

Direct GitHub installation of this development branch:

```bash
cd /path/to/ts-workspace
pi install -l git:github.com/iawnix/TSAgentSkill@pi_ts_subagents --approve
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

An unpinned GitHub URL resolves the repository default branch (`main`). Until
this work is merged or tagged, it does not select `pi_ts_subagents`.

Pi loads these extensions from the resolved package root:

- `extensions/ts-workflow-context`
- `extensions/ts-workflow-subagent`
- `extensions/ts-workflow-compute`
- `extensions/ts-workflow-artifacts`

The workspace control surface is exactly:

- `ts_workspace_context`: read `summary`, `delta`, `node`, `branch`, or
  `audit` context on demand.
- `ts_workspace_decide`: construct a non-mutating `ts-decision/2` draft with
  current report and revision provenance.
- `ts_workspace_validate`: validate that draft against the live workspace.
- `ts_workspace_apply`: transactionally apply a validated mutation and return
  refreshed compact context.

Pi also exposes:

- `ts_workspace_subagent`: fresh, tool-free advisory scientific review.
- `ts_workspace_compute_operator`: fresh backend operator with only the typed
  tools bound to one `prepare`, `submit`, `inspect`, `collect`, `cancel`, or
  `parse` request. `submit/cancel` require a fresh interactive host confirmation
  on every call and are unavailable in headless Pi sessions.
- `ts_workspace_render_operator`: node-scoped local render with bound paths.
- `ts_workspace_report_operator`: validated report-package build under
  `reports/`.
- `ts_workspace_email_operator`: local draft JSON from a generated report
  summary and explicit recipients. Sending is unavailable.

`before_agent_start` injects only a short control-plane reminder. It does not
inject a full workspace report every turn. Use `mode=delta` with the last
scientific `workspace_revision` and `operational_revision` to avoid repeated
unchanged context while still seeing new calculation or agent-run state.

See `references/pi_agent_adapter.md`.

## Research Nodes

New nodes use one `node_type`:

| Node type | Responsibility |
|---|---|
| `intake` | Normalize user inputs, structures, constraints, and completion criteria. Reserved for `n000`. |
| `mechanism` | Propose, compare, revise, or evaluate a falsifiable mechanism hypothesis. |
| `candidate_search` | Generate TS, endpoint-conformer, intermediate, or crossing-point candidates. |
| `validation` | Produce evidence for a declared prediction and `validation_scope`. |
| `audit` | Audit a TS, elementary step, pathway, or the study. |

Frequency and IRC/connectivity are both validation nodes but remain separate
evidence gates. Wavefunction analysis is normally
`node_type=validation, validation_scope=electronic_structure`; a later
`mechanism` node interprets whether that evidence supports or falsifies the
hypothesis.

Independent status axes:

- `node.lifecycle`: `running|closed|stopped`
- `closure.program.outcome`: `success|failure|not_run`
- `closure.hypothesis.status`: `supported|unsupported|ambiguous`, mechanism only
- `closure.audit.status`: `accepted|not_accepted|ambiguous`, audit only

Candidate and validation nodes cannot set hypothesis status.

## Calculation Attempts

New calculation intents use `ts-calculation-intent/2` and declare:

- `validation_scope`
- `attempt_kind=primary|retry|recalculation`
- `recalculation_ref`, required only for recalculation
- one allowlisted backend and task type
- a local or allowlisted remote execution target

Remote intents select `transport=ssh|mcp`. Legacy remote intents without the
field remain SSH-compatible. SSH policy comes from `TS_COMPUTE_*`; MCP
connection settings come only from `TS_CLUSTER_MCP_URL`,
`TS_CLUSTER_MCP_TOKEN`, and `TS_CLUSTER_MCP_TIMEOUT`. Endpoints and credentials
are forbidden in calculation intents.

All local authority for one attempt lives under:

```text
nodes/<node>/attempts/<intent>/
├── intent.json
├── prepared.json
├── status.json
├── submit_guard.json / submit_result.json
├── cancel_guard.json / cancel_result.json
└── outputs/
```

A remote directory must declare `authority=execution_mirror`. Results become
usable only after collection and local verification. See
`references/compute_operator.md`.

For scheduler-backed execution, the bundled TS Cluster MCP binds one
`submission_id` to the intent digest, complete input manifest, expected
artifacts, and resource request. It persists known scheduler IDs across
post-`qsub` failures and forbids automatic retry after ambiguous submission or
cancellation outcomes. Raw MCP tools are a host-side boundary and are not in
the Root or child inventories; the public compute operator creates one scoped
wrapper only after current-call authorization. Scheduler records are not
scientific evidence. Complete server installation, `cluster-mcp check`, token
mapping, SSH-tunnel and direct-HTTPS setup, Pi smoke testing, systemd operation,
and scope rules are in `references/cluster_mcp.md`.

## Agent Protocol

All isolated roles communicate through:

- `contracts/agent_task.schema.json` (`ts-agent-task/1`)
- `contracts/agent_result.schema.json` (`ts-agent-result/1`)

Roles are `review`, `backend`, `render`, `report`, and `email`. Results cannot
contain authoritative hypothesis, branch, acceptance, or strict pathway
decision fields. Private role skills live under `agent-skills/` and are loaded
only into the selected fresh child session.

The Pi host persists every child task under `nodes/<node>/agent-runs/<task>/`
for one-node work or `operations/agent-runs/<task>/` for study-level work.
These immutable operational records are never evidence and do not change the
scientific `workspace_revision`.

## Reporting

Generate the final package only from a validated workspace:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_report.py" \
  --root <workspace> \
  --package-dir <workspace>/reports/final_report_package
```

Package creation is no-overwrite and atomic. `package_manifest.json` uses
`ts-report-package/1` and binds the source `workspace_revision`, report,
context, email summary, and assets by SHA-256. Email drafting rejects a changed
manifest or summary.

Use `templates/ts_final_report.md`. Keep electronic, E+ZPE, and available free
energy values distinct; report missing corrections explicitly. Accepted-TS
language still requires separate TS/Freq, connectivity, and audit support.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run test:pi-adapter
npm pack --dry-run --json
```

The Pi integration suite runs the real Pi executable with a local recording
provider. It verifies the nine-tool Root Agent inventory, a tool-free review
child, a compute child with exactly one request-bound tool, and an artifact
child with exactly one request-bound tool. Before release, also test one clean,
branch- or tag-pinned GitHub installation from a network that can reach GitHub.
