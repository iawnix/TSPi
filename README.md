# TSAgentSkill

TSAgentSkill is an evidence- and hypothesis-driven transition-state research
workflow for Codex and Pi Agent. It separates scientific decisions, program
execution, evidence registration, branch topology, reporting, and read-only
visualization.

New work uses `ts-decision/2` and `ts-node/2`. Legacy phase-based workspaces
remain readable and closable, but they are not the model for new studies.

## Architecture

- `ts_workspace`: the only canonical research-state control plane.
- `ts_compute` and `ts_backends`: typed calculation intents, preparation,
  status, collection, and deterministic parsing.
- `subagents/`: fresh Pi review sessions and the shared
  `ts-agent-task/1` / `ts-agent-result/1` protocol.
- `agent-skills/`: private backend, render, report, and email skills. They are
  not registered in the root Pi/Codex skill inventory.
- `ts_render`: local molecular rendering through `xyzrender` only.
- `ts_report`: report-package assembly from validated workspace evidence.
- `ts_web`: read-only workspace normalization and visualization.

The Root Agent is the sole authority for hypothesis status, branch selection,
audit conclusions, stopping, and workspace decisions. A completed calculation
is only a program fact.

## Install

Clone or install the package, then create a workspace-owned runtime:

```bash
git clone https://github.com/iawnix/TSAgentSkill.git
export TS_AGENT_SKILL_ROOT=$PWD/TSAgentSkill
export TS_WORKSPACE_ROOT=/path/to/ts-workspace
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

Therefore separate Codex and Pi workspaces do not collide by default. Set the
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

## Codex Usage

Install or sync this package under a workspace skill directory such as:

```text
<workspace>/.agents/skills/transition-state-workflow/
```

Set an explicit package root for shell fallback commands:

```bash
export TS_AGENT_SKILL_ROOT=<workspace>/.agents/skills/transition-state-workflow
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_workspace --root <workspace>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_node --root <workspace> --node-id <node>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_branch_context --root <workspace> --from-node <trigger> --anchor-node <checkpoint>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_decision --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" start_node --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" update_workspace --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" end_node --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_workspace --root <workspace>
```

Read `references/decision_contract.md` before constructing new v2 decisions.
Do not edit `research_state.json`, `hypotheses.json`, or
`evidence_registry.json` by hand.

## Pi Agent Usage

The native adapters require Pi `0.81.1` and matching Pi SDK packages. Pi
project-local installation registers a package reference; it does not copy the
skill into a requested directory.

Local package reference:

```bash
cd /path/to/ts-workspace
pi install -l /absolute/path/to/TSAgentSkill --approve
```

Direct GitHub installation:

```bash
cd /path/to/ts-workspace
pi install -l https://github.com/iawnix/TSAgentSkill --approve
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

Pi loads these extensions from the resolved package root:

- `extensions/ts-workflow-context`
- `extensions/ts-workflow-subagent`
- `extensions/ts-workflow-compute`

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
  tools bound to one `prepare`, `inspect`, `collect`, or `parse` request.

`before_agent_start` injects only a short control-plane reminder. It does not
inject a full workspace report every turn. Use `mode=delta` after a known
revision to avoid repeated unchanged context.

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

All local authority for one attempt lives under:

```text
nodes/<node>/attempts/<intent>/
├── intent.json
├── prepared.json
├── status.json
└── outputs/
```

A remote directory must declare `authority=execution_mirror`. Results become
usable only after collection and local verification. See
`references/compute_operator.md`.

## Agent Protocol

All isolated roles communicate through:

- `contracts/agent_task.schema.json` (`ts-agent-task/1`)
- `contracts/agent_result.schema.json` (`ts-agent-result/1`)

Roles are `review`, `backend`, `render`, `report`, and `email`. Results cannot
contain authoritative hypothesis, branch, acceptance, or strict pathway
decision fields. Private role skills live under `agent-skills/` and are loaded
only into the selected fresh child session.

## Reporting

Generate the final package only from a validated workspace:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_report.py" \
  --root <workspace> \
  --package-dir <workspace>/reports/final_report_package
```

Use `templates/ts_final_report.md`. Keep electronic, E+ZPE, and available free
energy values distinct; report missing corrections explicitly. Accepted-TS
language still requires separate TS/Freq, connectivity, and audit support.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run test:pi-adapter
npm pack --dry-run --json
```
