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
- `mol_comparator`: structure comparison helpers.
- `ts_render`: lightweight molecular rendering through `xyzrender` only.
- `ts_report`: final report assembly from validated workspace evidence.
- `extensions/ts-workflow-context`: Pi Agent extension for workspace context,
  validation, and decision tools.
- `templates/decision/`: runtime decision JSON templates for workspace
  mutations. These are operating examples; files under `tests/` are not.
- `templates/ts_final_report.md`: fillable final-report template.

## Runtime Model

Python dependencies run in an isolated Conda or Mamba environment. Package
installation does not create that environment automatically. The user must
provide an existing Conda/Mamba installation root or executable.

Typical install:

```bash
git clone https://github.com/iawnix/TSAgentSkill.git
cd TSAgentSkill
python scripts/install_env.py --conda-root /path/to/miniforge3 --with-render --json
```

Equivalent environment variables:

```bash
TS_AGENT_CONDA_ROOT=/path/to/miniforge3 python scripts/install_env.py --with-render --json
TS_AGENT_CONDA_EXE=/path/to/conda python scripts/install_env.py --with-render --json
```

Useful runtime overrides:

```bash
TS_AGENT_ENV_ROOT=/path/to/env-store
TS_AGENT_PYTHON=/path/to/python
TS_AGENT_DISABLE_RUNTIME_REEXEC=1
```

The installer writes `.runtime/env.json`. Public Python scripts and the Pi
extension prefer the interpreter recorded there. If `environment.yml` changes,
stale runtime manifests are ignored until the environment is refreshed.

## Render Dependency Boundary

`ts_render` uses `xyzrender` only.

The skill does not require or probe Blender, FFmpeg, OpenBabel, Mayavi, or
PyVista. Install render support with:

```bash
python scripts/install_env.py --conda-root /path/to/miniforge3 --with-render --json
python scripts/ts_render.py diagnostic --json
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
python scripts/ts_workspace.py init_workspace --root <workspace>
python scripts/ts_workspace.py report_workspace --root <workspace>
python scripts/ts_workspace.py validate_decision --root <workspace> --decision-file decision.json
python scripts/ts_workspace.py start_node --root <workspace> --decision-file decision.json
python scripts/ts_workspace.py update_workspace --root <workspace> --decision-file decision.json
python scripts/ts_workspace.py end_node --root <workspace> --decision-file decision.json
python scripts/ts_workspace.py validate_workspace --root <workspace>
```

Run `report_workspace` before choosing or closing a node. Do not edit workspace
ledgers by hand.

Use `templates/decision/` when preparing runtime decision JSON. Replace the
`${NAME}` placeholders, run `validate_decision`, then apply the mutation. Do
not copy decision JSON from `tests/`; tests are fixtures and may intentionally
omit operating context. The templates constrain state-machine shape and
evidence provenance only, not a fixed retry policy.

## Pi Agent Usage

Install this checkout as a project-local Pi package from the TS workspace:

```bash
cd /path/to/ts-workspace
pi install -l /path/to/TSAgentSkill --approve
```

Install or refresh the runtime from the package root:

```bash
cd /path/to/TSAgentSkill
python scripts/install_env.py --conda-root /path/to/miniforge3 --with-render --json
```

Start Pi from the TS workspace:

```bash
cd /path/to/ts-workspace
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

Pi loads the root skill and `extensions/ts-workflow-context` from
`package.json`.

Pi commands:

```text
/ts-context [workspace]
/ts-validate [workspace]
```

Pi tools:

- `ts_workspace_context`: run `report_workspace` and return a compact summary.
- `ts_workspace_validate`: run `validate_workspace`.
- `ts_workspace_decision`: run `validate_decision`, `start_node`,
  `update_workspace`, or `end_node` through a decision JSON.

The Pi extension is a wrapper. Chemistry judgments, accepted-TS logic,
Gaussian parsing, workspace state transitions, and backtrack rules stay in the
Python kernel.

## Reporting

Use the final report template after the workspace validates:

```text
templates/ts_final_report.md
```

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
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_in_runtime.py -m pytest -q
```

Check Pi package contents:

```bash
npm pack --dry-run
```
