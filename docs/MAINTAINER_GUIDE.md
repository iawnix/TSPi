# Maintainer Guide

This guide covers the `@iawnix/ts-agent` Pi package. Edit the authored checkout,
not a Pi-managed installation or runtime copy.

## Architecture Rule

Preserve this boundary:

```text
Root Agent: research strategy and scientific interpretation
Workspace Kernel: contracts, refs, Evidence facts, Gates, transactions
Operators: bounded execution and operational journals
```

A schema enum is justified only when code must execute a closed deterministic
contract. Node categories, workflow stages, Evidence roles, and provider-facing
scientific layers are not such contracts.

## Package Boundary

- `package.json.pi.skills` registers only
  `skills/transition-state-workflow/`.
- Child policies under `src/agents/` are private runtime inputs, not Skills.
- `package.json.pi.extensions` is the public Pi adapter surface.
- Public prefixes are strict:
  - `ts_workspace_*`: deterministic workspace control;
  - `ts_subagent_*`: fresh child model session;
  - `ts_remote_*`: deterministic infrastructure diagnostics.
- Do not add compatibility aliases to normal runtime surfaces.
- Keep `package.json.files` explicit and `private: true` until publication is
  authorized.

## Module Ownership

- `ts_workspace` exclusively owns canonical scientific writes.
- `ts_workspace/decision_validator_v3.py` validates decision shape and live
  refs.
- `ts_workspace/validator_v3.py` validates the persisted workspace.
- `ts_workspace/gates_v3.py` evaluates closed fact policies and audit Gate
  sets.
- `ts_workspace/reader_v3.py` builds read-only Agent/report projections.
- `ts_workspace/operational.py` indexes calculation and child-run state without
  changing the scientific revision.
- `ts_compute/capabilities.py` describes typed adapter support. It is not a
  strategy ranking or live readiness probe.
- `ts_backends` prepares and parses program artifacts without making Claim or
  Gate decisions.
- `ts_remote` owns OpenSSH/SCP, Torque control, transfer verification, and
  scheduler records without chemistry interpretation.
- `ts_report` assembles validated immutable report packages.
- `ts_web` reads source workspaces and writes only its explicit UI registry.
- `extensions/ts-workflow-control` exposes read, draft, validate, and apply.
- `extensions/ts-workflow-review` owns bounded advisory Review and Root
  disposition.
- `extensions/ts-workflow-compute` owns fresh request-scoped compute sessions.
- `extensions/ts-workflow-artifacts` owns render/report sessions and
  deterministic notifications.
- `extensions/ts-workflow-ui` is presentation-only and exclusively owns the
  TSPi header, editor, footer, activity panel, and child history.
- `src/agent-core` owns cross-agent task/result contracts and immutable
  journals.
- `src/agents/review` owns Review packet projection and result validation.
- `src/agents/compute` and `src/agents/artifacts` own private operator policy
  composition.

## V3 Scientific Model

The long-lived model has four concepts:

- Node: bounded act and parent topology;
- Claim: Root-authored scientific statement;
- Evidence: immutable facts and provenance;
- Gate: deterministic fact-policy result.

Keep Claim and Evidence `kind` values open and versioned. Add a closed Gate only
when a deterministic evaluator and a real acceptance requirement exist.

Node tags must never select an allowed action, backend, next Node, or closure
shape. Compute capability entries must never prescribe method order. A new
scientific strategy should normally require documentation and Root reasoning,
not another Kernel enum.

## Mutation Invariants

- New state uses `ts-decision/3` and `ts-node/3` only.
- Apply validates internally while holding the workspace lock.
- Root state files are never edited by extensions, operators, renderers, or web
  code.
- Decision IDs are content-addressed idempotency keys for committed
  transactions.
- Transaction order remains prepare, decision snapshot, proposed writes,
  decision log, committed.
- Full dry-run validation must use the same mutation path as apply.
- Accepted artifacts require a named audit policy and passing, target-compatible
  Gate results.
- Pending Review disposition is an operational obligation, not a scientific
  state transition.

The explicit v2-to-v3 copy migration may read old fields. No other module, test
fixture, documentation example, or normal command should produce them.

## Agent Contracts

Every child uses `ts-agent-task/2` and `ts-agent-result/1`. Scope is report,
Node, and Claim refs. Results cannot set Claim status, Gate verdicts, audits,
accepted refs, or study completion.

Review uses:

- `ts-review-evidence-snapshot/2`: full host validation basis;
- `ts-review-provider-input/2`: compact deterministic model projection;
- exactly one `ts_review_result` tool;
- at most one same-session format repair;
- provider failure priority over missing-tool or schema failure.

Invalid output is a mode-0600 bounded operational journal artifact and must
never enter Evidence or reports automatically.

## Compute And Remote Contracts

Preparation resolves logical artifact IDs and roles into immutable local refs
and writes `ts-calculation-intent/3`. The Root Agent owns scientific method and
resources; adapters own generated files and allowed request shapes.

Distinguish:

- request validation or upload failure before scheduler effect;
- scheduler request started with unknown result;
- known job ID followed by transport failure;
- program failure after confirmed execution;
- report serialization failure after a typed action.

Never map a structured return to action success by default.

`ts_remote` is the only remote subsystem. Remote requests bind one configured
profile, workspace identity, immutable input manifest, expected artifacts,
resource request, and submission ID. Preserve known job IDs, fail closed on
ambiguous effects, and collect declared files without scheduler-history
coupling.

## Documentation And Tests

Contract changes must update together:

- JSON schemas;
- Python/CJS/TypeScript validators;
- decision templates;
- Skill and focused references;
- Python unit tests;
- real-Pi recording-provider integration tests;
- report/web projections;
- package allowlist checks.

Documentation tests should assert architecture invariants and public entrypoints,
not freeze prose or reintroduce removed concepts.

Normal TSPi sessions load only `.pi/packages/ts-agent/current` and force
`TS_PACKAGE_SOURCE_MODE=research`: Root Agents learn public calls from
registered schemas, live capabilities, the Skill, and focused references.
Source development requires both `TS_PACKAGE_DEV_ROOT` and an explicit authored
launcher; it defaults to maintenance mode. Tests remain verification material
and must not be the only source of a public usage example.

Build releases only from a clean authored checkout. `--allow-dirty` exists for
local validation and must not be used for a published artifact:

```bash
python3 scripts/build_release.py --output-dir dist --json
python3 scripts/install_release.py \
  --manifest dist/ts-agent-release.json \
  --install-root /path/to/TSPi-installation \
  --json
```

The release is content-addressed and installation is an atomic pointer switch.
Keep previous release directories; rollback is performed by installing or
selecting a previously validated release, not by editing its contents. Runtime
archives must exclude tests, maintainer documents, build/check scripts, Git
metadata, caches, and dependency trees.

## Release Validation

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run typecheck
npm run test:pi-adapter
npm run test:package
npm pack --dry-run --json
python3 scripts/check_package.py
python3 scripts/build_release.py --output-dir dist --json
git diff --check
```

Also run the Skill validator against
`skills/transition-state-workflow/`. Before claiming installation parity,
verify the live Pi package reference or synchronize only after explicit user
authorization.
