# TSAgentSkill

TSAgentSkill is a transition-state search skill for Codex and Pi Agent. It
keeps the Python workflow kernel authoritative and exposes thin agent adapters
around the same source tree.

The workflow is evidence-layered: candidate generation, TS/Freq validation,
connectivity or IRC validation, accepted-TS audit, and pathway audit are
reported as separate scientific claim layers. A rendered image is only a
visualization artifact, not chemistry proof.

## What Is Included

- `SKILL.md`: Codex skill entrypoint and operating contract.
- `ts_workspace`: workspace bootstrap, validated decision mutations, reporting,
  finalizers, and workspace validation.
- `ts_backends`: local calculation adapters and parsers.
- `ts_remote`: remote staging, submission, polling, fetch, and kill helpers.
- `ts_structures`: structure parsing, geometry, RMSD, and stereochemistry helpers.
- `ts_render`: lightweight molecular rendering through `xyzrender` only.
- `ts_report`: final report package assembly from validated workspace evidence.
- `extensions/ts-workflow-context`: Pi Agent extension for workspace context,
  validation, and decision tools.
- `extensions/ts-workflow-subagent`: Pi 0.81.1+ extension for isolated,
  tool-free scientific review sessions.
- `templates/decision/`: runtime decision JSON templates for workspace
  mutations. These are operating examples; files under `tests/` are not.
- `templates/ts_final_report.md`: fillable final-report template.
- `docs/MAINTAINER_GUIDE.md`: code-maintenance guide for module boundaries,
  control-plane invariants, testing, and release sync.

## Runtime Model

Python dependencies run in an isolated Conda or Mamba environment. Package
installation does not create that environment automatically. The user must
provide an existing Conda/Mamba installation root or executable.

Typical install:

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

Equivalent environment variables:

```bash
TS_AGENT_CONDA_ROOT=/path/to/miniforge3 python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" --package-root "$TS_AGENT_SKILL_ROOT" --workspace-root "$TS_WORKSPACE_ROOT" --with-render --json
TS_AGENT_CONDA_EXE=/path/to/conda python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" --package-root "$TS_AGENT_SKILL_ROOT" --workspace-root "$TS_WORKSPACE_ROOT" --with-render --json
```

Useful runtime overrides:

```bash
TS_WORKSPACE_ROOT=/path/to/ts-workspace
TS_AGENT_RUNTIME_HOME=/path/to/runtime-home
TS_AGENT_RUNTIME_MANIFEST=/path/to/env.json
TS_AGENT_ENV_ROOT=/path/to/env-store
TS_AGENT_PYTHON=/absolute/path/to/python
TS_AGENT_DISABLE_RUNTIME_REEXEC=1
```

The installer writes the runtime manifest outside the package checkout by
default. With `--workspace-root`, the default is
`<workspace>/.agents/runtime/transition-state-workflow/env.json` and the Conda
prefix store is `<workspace>/.agents/envs/transition-state-workflow/`. Public
Python scripts and the Pi extension prefer the interpreter recorded there. If
`environment.yml` changes, stale runtime manifests are ignored until the
environment is refreshed. Legacy `package-root/.runtime/env.json` manifests are
read only when no explicit workspace root, runtime home, or manifest path is
supplied.

From a package checkout, the npm helper scripts require `TS_WORKSPACE_ROOT` and
write the same workspace-owned runtime:

```bash
cd "$TS_AGENT_SKILL_ROOT"
TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env
TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env:core
```

## Render Dependency Boundary

`ts_render` uses `xyzrender` only.

The skill does not require or probe Blender, FFmpeg, OpenBabel, Mayavi, or
PyVista. Install render support with:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" --package-root "$TS_AGENT_SKILL_ROOT" --workspace-root "$TS_WORKSPACE_ROOT" --conda-root /path/to/miniforge3 --with-render --json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" diagnostic --json
```

If `xyzrender` is unavailable, TS workspace operations, validation, and reports
still work; only render artifact generation is unavailable.

## Codex Usage

Use this repository as a Codex skill by installing or syncing it under the
workspace skill directory, for example:

```text
<workspace>/.agents/skills/transition-state-workflow/
```

Codex reads `SKILL.md` as the skill entrypoint. Public workspace commands:

```bash
export TS_AGENT_SKILL_ROOT=<workspace>/.agents/skills/transition-state-workflow
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" init_workspace --root <workspace>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_workspace --root <workspace>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_node --root <workspace> --node-id <node>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_branch_context --root <workspace> --from-node <trigger> --anchor-node <checkpoint>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" migrate_workspace_state --root <legacy-workspace>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_decision --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" start_node --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" propose_hypothesis --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" update_workspace --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" end_node --root <workspace> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_workspace --root <workspace>
```

Run `report_workspace` before choosing or closing a node. Do not edit workspace
state files by hand.

Canonical root state is limited to `research_state.json`, `hypotheses.json`,
and `evidence_registry.json`. Knowledge summaries and reports are derived.

The active flow is endpoint validation -> `propose_hypothesis` -> first
evidence node. A proposal mutates `hypotheses.json` but does not create a
node. Reporting, monitoring, snapshots, visualization, and report packaging do
not create nodes either.

Use `templates/decision/` when preparing runtime decision JSON. Replace the
`${NAME}` placeholders, run `validate_decision`, then apply the mutation. Do
not copy decision JSON from `tests/`; tests are fixtures and may intentionally
omit operating context. The templates constrain state-machine shape and
evidence provenance only, not a fixed retry policy.

## Pi Agent Usage

The native subagent integration requires Pi `0.81.1` and matching
`@earendil-works/pi-ai` / `@earendil-works/pi-coding-agent` packages.

Install the package project-locally from the TS workspace. For maintained local
workspaces, prefer registering the installed skill copy so Pi and Codex share
the same package root:

```bash
cd /path/to/ts-workspace
pi install -l "$PWD/.agents/skills/transition-state-workflow" --approve
```

Direct GitHub installation is also supported; the package checkout then lives
under `.pi/git/...`, but runtime state still belongs to the TS workspace when
`TS_WORKSPACE_ROOT` is set:

```bash
pi install -l https://github.com/iawnix/TSAgentSkill --approve
```

For GitHub installs, use the Pi-managed checkout path as `TS_AGENT_SKILL_ROOT`
when refreshing the runtime, or run the npm helper from that checkout with
`TS_WORKSPACE_ROOT` set.

Install or refresh the runtime with an explicit package root and workspace root:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/TSAgentSkill
export TS_WORKSPACE_ROOT=/path/to/ts-workspace
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" --package-root "$TS_AGENT_SKILL_ROOT" --workspace-root "$TS_WORKSPACE_ROOT" --conda-root /path/to/miniforge3 --with-render --json
```

Start Pi from the TS workspace:

```bash
cd /path/to/ts-workspace
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

Pi loads the root skill, `extensions/ts-workflow-context`, and
`extensions/ts-workflow-subagent` from `package.json`.

Pi commands:

```text
/ts-context [workspace]
/ts-validate [workspace]
```

Pi tools:

- `ts_workspace_context`: return the compact workspace summary; pass `nodeId`
  for a historical-node capsule or `fromNode` plus `anchorNode` for a
  backtrack comparison.
- `ts_workspace_validate`: run `validate_workspace`.
- `ts_workspace_decision_validate`: preflight a decision JSON without mutation.
- `ts_workspace_decision`: run `start_node`, `propose_hypothesis`,
  `update_workspace`, or `end_node` through a decision JSON.
- `ts_workspace_subagent`: run one bounded advisory review in a fresh,
  in-memory, tool-free child session.

The Pi extensions are wrappers. Chemistry judgments, accepted-TS logic,
Gaussian parsing, workspace state transitions, and branch-context rules stay in
the Python kernel.

## Reporting

Use the final report template after the workspace validates:

```text
templates/ts_final_report.md
```

Generate a report package when handing off a completed search:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_report.py" --root <workspace> --package-dir <workspace>/reports/final_report_package
```

The package contains `final_report.md`, `report_context.json`, `assets/`, and
`email_summary.md`. The report should include R-TS-P structure references,
imaginary-mode/vibration analysis, IRC key-distance evidence, an energy profile
with electronic, E+ZPE, and available free-energy relative values or explicit
missing-energy notes, and a mechanism interpretation that separates accepted
pathway evidence from chemical speculation.

The report must state the highest validated evidence layer reached. Do not call
a candidate, scan point, NEB image, dMECP structure, or isolated imaginary
frequency an accepted TS. Accepted-TS language requires TS/Freq and
connectivity evidence for the same hypothesis plus an accepted-audit artifact.

See:

- `references/report_template.md`
- `references/runtime_environment.md`
- `references/render_contract.md`
- `references/pi_agent_adapter.md`

## Validation

Run local tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
```

Run tests through the configured runtime:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 "$TS_AGENT_SKILL_ROOT/scripts/ts_runtime.py" run -m pytest -q
```

Check Pi package contents:

```bash
npm pack --dry-run
```
