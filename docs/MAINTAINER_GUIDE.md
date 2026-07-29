# Maintainer Guide

This guide is for changing TSAgentSkill code. It complements `SKILL.md`,
`README.md`, and the files in `references/`; it does not replace them.

The central rule is simple: the Python workspace kernel is the authority for
state integrity, while agents decide research direction from reports,
templates, and chemistry evidence.

## Source Of Truth

- Edit the maintenance repository, not an installed copy:
  `/home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor`.
- The installed Codex skill copy is deployment output:
  `/home/iaw/TS/.agents/skills/transition-state-workflow`.
- `SKILL.md` is the Codex entrypoint and operating contract.
- `references/` holds focused contract notes for humans and agents.
- `templates/decision/` holds runtime decision JSON starting points.
- `tests/` holds regression fixtures only. Do not treat test JSON as live
  operating examples.

## Module Ownership

Keep state ownership narrow.

- `ts_workspace` is the only writable control plane. It owns workspace
  initialization, validated decision mutations, finalizers, workspace readers,
  and validators.
- `ts_workspace/validators` checks decision shape, workspace context, and
  workspace integrity. Validators may reject corrupting writes, but they must
  not decide chemistry strategy.
- `ts_workspace/finalizers` derives state updates that are consequences of an
  accepted close decision, such as accepted-audit facts.
- `ts_workspace/readers` builds read-only summaries such as
  `report_workspace`.
- `ts_backends` prepares inputs and parses backend artifacts. It must not write
  workspace verdicts, accepted TS facts, or branch decisions.
- `ts_remote` stages, submits, polls, fetches, and kills remote jobs. It must
  not interpret chemistry.
- `ts_structures` analyzes structures and returns evidence-shaped diagnostics.
  It must not mutate workspace state.
- `ts_render` writes visualization artifacts only. It must not mutate root
  state files or make chemistry claims.
- `ts_web` reads source workspaces and writes only its explicit registry or UI
  state under `--state-dir`. Its `--state-dir` must not be inside any source
  workspace.
- `ts_report` assembles final report packages from validated evidence. Missing
  evidence should be stated explicitly, not silently inferred.
- `extensions/ts-workflow-context` is an adapter. Keep authority in the Python
  kernel and expose it through thin Pi tools.

## Control-Plane Invariants

Preserve these invariants when changing `ts_workspace`:

- Every mutation command must validate its decision internally.
- `decision.action` must match the invoked mutation command.
- Except first-time bootstrap, mutating work must be traceable to a decision
  JSON. Destructive `init_workspace --force` requires an
  `action=init_workspace` decision.
- Root state files are not edited by agents or helper modules. All root state
  mutations go through `ts_workspace`.
- Canonical scientific state is limited to `research_state.json`,
  `hypotheses.json`, and `evidence_registry.json`; Markdown knowledge and
  reports are generated views.
- `decisions/<decision_id>.json` is the full submitted decision snapshot.
- Reusing a `decision_id` is allowed only for identical decision content with
  an already committed transaction; the retry is a no-op.
- Different content with the same `decision_id` is rejected before mutation.
- A transaction record without a matching decision snapshot blocks automatic
  replay of that `decision_id`.
- Transaction order is:
  1. append `transaction_log.jsonl` `prepare`;
  2. write the decision snapshot;
  3. apply proposed state writes;
  4. append the `decision_log.jsonl` row;
  5. append `transaction_log.jsonl` `committed`.
- `validate_workspace` reports pending transactions as warnings so maintainers
  can inspect state manually; it should not hide or auto-repair them.

## Chemistry Policy Boundary

Hard-code only rules that protect state integrity or evidence contracts.

Good hard errors:

- invalid schema shape;
- missing required provenance;
- references to non-existent nodes, hypotheses, evidence, or paths;
- cross-file topology contradictions;
- evidence paths that point into a different node's artifact directory;
- accepted-audit or pathway-audit gates without required evidence.

Prefer warnings, templates, or references for research strategy:

- whether to retry a failed calculation;
- whether a route failure means a new solution, new hypothesis, or stop;
- whether QST, scan, NEB, dMECP, or another backend is the right next method;
- whether a negative pathway audit exhausts the task.

When in doubt, keep the code conservative: enforce recoverable state, surface
diagnostics, and leave chemistry direction to the agent after
`report_workspace`.

## Adding Or Changing State

Use this checklist for state-model changes.

- Update JSON schemas under `ts_workspace/contracts/`.
- Update pure decision validation in `ts_workspace/validators/decision.py`.
- Update workspace-aware validation in
  `ts_workspace/validators/decision_context.py` when references depend on
  current workspace state.
- Update `ts_workspace/validators/workspace.py` for persisted workspace
  integrity.
- Update finalizers only when a close decision should deterministically derive
  model updates.
- Update `ts_workspace/readers/report.py` if agents need the new state in
  `report_workspace`.
- Update `ts_web/normalize.py` only after the authoritative read shape exists.
- Update decision templates in `templates/decision/`.
- Update references and tests in the same change.

Avoid parallel vocabularies. If a label, color, `claim_state`, or status is
needed by the browser and another reader, derive it once in a Python read layer
and have `ts_web` consume that result.

## Web Explorer Rules

`ts_web` is read-only with respect to source workspaces.

- Do not write root state files from `ts_web`.
- Do not let browser JavaScript invent chemistry vocabulary or derive
  workspace status that the Python read layer does not provide.
- Keep compatibility shims for old registry rows local to registry/read
  normalization code. New writes should use `workspace_id`, `source_root`, and
  `label`.
- Batch registration must validate every source workspace against `state_dir`
  before creating or updating registry files.
- Keep file-preview endpoints path-safe, size-limited, and read-only.

## Backend, Remote, Runtime, And Render Rules

- Backends may prepare commands and parse artifacts; they must not write node
  closure, accepted facts, pathway acceptance, or branch decisions.
- Remote helpers should return receipts, statuses, fetched files, or errors.
  They should not infer mechanism identity.
- Runtime setup must stay isolated from shared Conda `base`. Public scripts
  should resolve the workspace-owned runtime manifest when a workspace root is
  known and fall back to the current interpreter for development checkouts.
  Legacy `package-root/.runtime/env.json` is compatibility input only when no
  explicit workspace root, runtime home, or manifest path is supplied.
- `ts_render` depends on `xyzrender` only. Do not add Blender, FFmpeg,
  OpenBabel, Mayavi, or PyVista probes unless the contract is intentionally
  revised.

## Testing Matrix

Run focused tests while developing, then the full suite before handoff.

Control plane:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_contracts.py \
  tests/test_workspace_validator.py \
  tests/test_hypothesis_contract.py \
  tests/test_acceptance_gates.py \
  tests/test_decision_templates.py \
  tests/test_workspace_cli.py \
  -p no:cacheprovider
```

Web explorer:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ts_web.py \
  tests/test_module_boundaries.py \
  -p no:cacheprovider
```

Reports:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ts_report.py \
  tests/test_report_template_contract.py \
  -p no:cacheprovider
```

Runtime, render, remote, and Pi adapter:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_runtime_env.py \
  tests/test_ts_render.py \
  tests/test_remote_job_lifecycle.py \
  tests/test_pi_agent_adapter.py \
  -p no:cacheprovider
```

Required before syncing or publishing:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

If the installed runtime matters:

```bash
export TS_AGENT_SKILL_ROOT=$PWD
export TS_WORKSPACE_ROOT=/path/to/ts-workspace
PYTHONDONTWRITEBYTECODE=1 python3 "$TS_AGENT_SKILL_ROOT/scripts/ts_runtime.py" run -m pytest -q
python3 "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" diagnostic --json
```

If Pi package metadata, extension files, or `package.json` changed:

```bash
npm pack --dry-run
```

## Release And Sync Procedure

Use this flow for maintained skill changes.

1. Edit the maintenance repository.
2. Run focused tests and the full pytest suite.
3. Commit with a message that names the contract or module changed.
4. Push `main` to `https://github.com/iawnix/TSAgentSkill`.
5. Sync the installed skill copy:

```bash
rsync -a --delete \
  --exclude .git \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude .runtime \
  /home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor/ \
  /home/iaw/TS/.agents/skills/transition-state-workflow/
```

6. Validate the installed copy:

```bash
cd /home/iaw/TS
export TS_AGENT_SKILL_ROOT=/home/iaw/TS/.agents/skills/transition-state-workflow
export TS_WORKSPACE_ROOT=/home/iaw/TS
python3 "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --workspace-root "$TS_WORKSPACE_ROOT" \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
PYTHONDONTWRITEBYTECODE=1 python3 "$TS_AGENT_SKILL_ROOT/scripts/ts_runtime.py" run -m pytest -q
python3 "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" diagnostic --json
```

7. If the behavior affects active research, record any remaining discrepancy in
   `/home/iaw/TS/.TODO.md`.

## Review Checklist

Before merging or syncing, answer these questions:

- Does the change preserve the single writable control plane?
- Are mutation decisions still fully auditable?
- Can an interrupted mutation be detected without silent replay?
- Are old workspaces either supported intentionally or rejected clearly?
- Does `report_workspace` expose enough context for the next agent decision?
- Did any new chemistry heuristic become a hard-coded policy by mistake?
- Did `ts_web` remain read-only over source workspaces?
- Are templates updated without copying test fixtures into operating examples?
- Are tests covering the failure mode, not only the successful path?
- Does the installed skill copy match the maintenance source after sync?
