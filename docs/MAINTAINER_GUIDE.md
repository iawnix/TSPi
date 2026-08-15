# Maintainer Guide

This guide covers development, validation, release, and documentation ownership
for `@iawnix/ts-agent`. Make changes in the authored Git checkout. Installed
releases are immutable runtime artifacts and must never be patched in place.

Read [Architecture](ARCHITECTURE.md) before changing a cross-module contract and
[Installation and Operations](INSTALLATION.md) before changing release, startup,
configuration, upgrade, or rollback behavior.

## Non-Negotiable Boundary

```text
Root Agent: research strategy and scientific interpretation
Workspace Kernel: canonical state, refs, fact policies, and transactions
Review Agent: bounded independent advice
Operators: pre-bound execution and operational journals
Infrastructure: configured transport, scheduler, delivery, and UI projection
```

Only `ts_workspace` writes canonical scientific state. A schema enum is
justified only when code must execute a closed deterministic contract. Node
categories, workflow phases or stages, Evidence roles or layers, and strategy
rankings do not belong in the Kernel.

Review is a scientific reasoning Agent. Compute, Render, and Report currently
use fresh child model sessions, but they are constrained operators: the host
binds their action and deterministically owns the effect and result authority.
Do not describe all child sessions as equivalent scientific Agents.

## Repository Map

| Path | Owner and purpose |
| --- | --- |
| `skills/transition-state-workflow/` | only public Pi Skill, focused Root references, and reusable assets |
| `extensions/ts-workflow-control/` | context, Decision draft/validate/apply, and package-source guard |
| `extensions/ts-workflow-review/` | advisory Review entrypoint and Root disposition |
| `extensions/ts-workflow-compute/` | typed compute operator and read-only remote diagnostics |
| `extensions/ts-workflow-artifacts/` | Render, Report, and deterministic notification entrypoints |
| `extensions/ts-workflow-ui/` | header, editor, footer, activity, and child history only |
| `extensions/shared/` | public tool inventory and shared presentation/path helpers |
| `src/agent-core/` | Agent task/result validation, failure taxonomy, session lifecycle, journals |
| `src/agents/review/` | Review packet projection, prompts, result tool, semantic validation |
| `src/agents/compute/` | private compute operator policy and runtime |
| `src/agents/artifacts/` | private Render/Report operator policy and runtime |
| `ts_workspace/` | v3 canonical state, bootstrap, readers, validators, Gates, transactions |
| `ts_compute/` | calculation capability, artifact catalog, intents, control, collection |
| `ts_backends/` | deterministic backend preparation and parsing |
| `ts_remote/` | OpenSSH/SCP, Torque, transfer, diagnostics, and control records |
| `ts_runtime/` | runtime resolution and TSPi Python lifecycle host |
| `ts_render/`, `ts_report/`, `ts_email/` | deterministic artifact and delivery services |
| `ts_structures/` | pure molecular structure comparison |
| `ts_web/` | read-only workspace projection and external UI registry |
| `contracts/` | shared Agent and Review JSON schemas |
| `docs/` | human installation, architecture, and maintenance documentation |
| `tests/` | unit, contract, package, and real-Pi recording-provider regression tests |

`TSPi` remains a thin shell shim. Lifecycle logic belongs in
`scripts/tspi_host.py` and `ts_runtime/launcher.py`; do not move configuration,
bootstrap, locking, or Pi argument construction back into shell.

## Public Package Surface

`package.json` registers exactly:

- one Skill: `skills/transition-state-workflow/`;
- five normal extensions: control, UI, Review, compute, and artifacts;
- one theme: `themes/ts-theme.json`.

`ts-phone-bridge` is packaged but loaded only by `TSPi --phone`. Private files
under `src/agents/` are prompt/policy fragments, not discoverable Skills.

Public prefixes are semantic:

- `ts_workspace_*`: deterministic workspace read or mutation pipeline;
- `ts_subagent_*`: one fresh bounded child model session;
- `ts_remote_*`: deterministic read-only infrastructure diagnostics;
- `ts_review_disposition`: deterministic operational response;
- `ts_notify_user`: deterministic fixed-target external delivery.

Do not add compatibility aliases to the normal runtime. The explicit v2-to-v3
copy migrator may read old fields; no normal tool, fixture, example, or report
projection should produce them.

The release ships `README.md`, all three `docs/*.md` guides, the Root Skill,
focused references, private operator policies, and executable runtime code. It
excludes tests, build/check scripts, Git metadata, dependency trees, caches,
credentials, sessions, and workspaces.

## V3 Scientific Model

The stable model is Node, Claim, Evidence, and Gate:

- Node records a bounded act and parent topology. Tags are descriptive only.
- Claim records a Root-authored statement, required Gates, cited facts, status,
  and history.
- Evidence records immutable facts and provenance without a workflow role or
  layer.
- Gate records one deterministic evaluator result for one target.

Node tags must never select an allowed action, backend, next Node, or closure
shape. They remain display and search metadata.

Keep Claim and Evidence `kind` values open and versioned. Add a closed Gate only
when both a deterministic evaluator and a real scientific or acceptance
requirement exist. A new strategy should normally require Root reasoning and
focused documentation, not a Kernel enum.

## Mutation Invariants

- New state uses `ts-decision/3` and `ts-node/3` only.
- Startup bootstrap initializes fresh state once and otherwise validates without
  canonical rewrites.
- `ts_workspace_decision_draft` allocates technical Decision, Evidence, and
  Gate-result IDs and binds the live report/revision.
- Draft callers still own Claim IDs, facts, targets, scientific rationale, and
  cited refs.
- Validate performs a complete non-mutating post-state dry run.
- Apply repeats workspace-aware validation while holding the lock.
- Do not edit a drafted Decision between validate and apply.
- Decision IDs are Kernel-issued idempotency keys bound to exact canonical
  Decision content.
- Transaction order remains prepare, Decision snapshot, proposed file writes,
  Decision log, committed record.
- Accepted artifacts require one named audit policy and current,
  target-compatible passing Gate results.
- Pending Review disposition is an operational obligation, not scientific
  state.

Root state files must never be edited by extensions, operators, backends,
remote code, renderers, reports, notification code, UI, or web projection.

## Agent And Operator Contracts

Every child session uses `ts-agent-task/2` and `ts-agent-result/1`. Scope is
limited to report, Node, and Claim refs. Results cannot set Claim status, Gate
verdicts, audit results, accepted refs, focus Claims, Decisions, or study
completion.

### Review

Review uses:

- `ts-review-evidence-snapshot/2` as the full local validation basis;
- `ts-review-provider-input/2` as the bounded model projection;
- exactly one `ts_review_result` tool;
- forced named tool choice without provider-side strict mode;
- local TypeBox and semantic validation;
- at most one same-session format repair;
- provider HTTP/stream failure priority over missing-tool or schema failure.

Unknown Evidence roles or layers must not be reintroduced into Review. Review
dependencies are derived from Claim refs and the Kernel snapshot. Citation
allowlists are canonical sets and must not depend on registry insertion order.

Invalid Review output is a bounded mode-0600 operational artifact and must never
enter Evidence, accepted artifacts, or reports automatically.

### Compute, Render, And Report

The Root and host bind each operator's operation, inputs, paths, capabilities,
and allowed side effects before child creation. Request-scoped tools must remain
narrow. Compute may summarize typed operational facts; Render and Report results
are host-generated from actual outputs. Never let model text become the
authoritative action result.

Distinguish:

- typed tool return from action success;
- pre-effect validation or staging failure from ambiguous external effect;
- known job ID from unknown scheduler result;
- program failure from scientific contradiction;
- artifact action success from outer report serialization failure.

Never map a structured return to success just because a tool call completed.

## Runtime Durability Semantics

Do not document stronger durability than the implementation provides:

- `beginAgentRun()` atomically writes the task and bound Review documents;
- `actions.json`, `result.json`, and `run.json` are written only during normal
  terminal handling;
- a process crash in between is indexed as a pending/unknown run;
- action arrays are accumulated in memory and are not a per-effect write-ahead
  log;
- `TS Activity` is transient and is cleared at session start/shutdown;
- `/ts-subagent-history` reads durable summaries on demand;
- synchronous tool return is the current result-delivery channel; no durable
  delivery acknowledgement or automatic replay exists.

Remote controls have separate guards and receipts. Recovery code must inspect
those records rather than treating child-run completion as scheduler authority.

Review has explicit provider response observation. Compute and artifact
operators currently rely on errors propagated by Pi for upstream model failure
classification. Preserve this distinction until the runtimes share one common
provider-observation implementation.

## Compute And Remote Contracts

Preparation resolves logical `artifactId` and `inputRole` pairs, validates
digests, generates adapter-owned files, and writes immutable
`ts-calculation-intent/3`. The Root Agent owns scientific purpose, method,
settings, execution target, and resources. It does not own generated paths,
filenames, expected artifacts, remote directories, or submission IDs.

`ts_compute/capabilities.py` is static adapter support, not a strategy ranking
or live readiness result. Backends prepare and parse program artifacts without
making Claim or Gate decisions.

`ts_remote` is the only remote subsystem. It binds an installation-owned
profile, workspace identity, manifest, script, expected artifacts, resources,
and submission ID. Preserve known job IDs, separate scheduler and program
state, fail closed on ambiguous effects, and collect without scheduler-history
coupling.

## Documentation Ownership

Maintain one owner for each kind of explanation:

| Document | Audience | Owns |
| --- | --- | --- |
| `README.md` | first-time reader | product boundary, quick install/start, public surface, navigation |
| `docs/INSTALLATION.md` | installation operator | prerequisites, config, startup, resume, upgrade, rollback, recovery |
| `docs/ARCHITECTURE.md` | maintainer and advanced operator | ownership, lifecycle, persistence, context, result delivery |
| `docs/MAINTAINER_GUIDE.md` | contributor/releaser | source workflow, change matrix, validation, release discipline |
| Root `SKILL.md` | Root Agent | concise authority rules and operating loop |
| Skill `references/*.md` | Root Agent on demand | one focused scientific or tool topic |
| `src/agents/**/*.md` | private child runtime | minimum role/backend policy loaded into one child session |
| JSON schema/tool schema | callers and validators | exact fields, enums, limits, and identity |

Do not copy field-level schemas into prose. Use examples only where they clarify
an interaction and test them against the real validator. Do not make tests the
only available public example.

Normal TSPi research sessions learn package operation from registered schemas,
live context/capabilities, the Root Skill, and focused references. They do not
inspect source, tests, or maintainer documents to infer calls.

## Contract Change Matrix

When a shared contract changes, inspect and update every applicable row:

| Change | Required surfaces |
| --- | --- |
| Decision or scientific record | JSON schema, Python validator/engine, templates, Skill/reference, report/web projection, tests |
| Gate | policy JSON, evaluator, audit policy if applicable, docs, fixtures, tests |
| Public tool | tool catalog, extension schema/help, Root Skill/README/architecture, UI presentation, real-Pi inventory tests |
| Agent task/result | JSON schema, CJS validator, runtime builder, journal/history projection, integration tests |
| Backend capability | capability catalog, request validator, adapter, private backend policy, compute reference, parser tests |
| Remote behavior | config/model, lifecycle/transfer, operator mapping, installation/remote docs, recovery tests |
| Release contents | `package.json.files`, package checker, installer allow/deny lists, package tests, installation docs |
| Startup behavior | Python host, shell-shim tests, installation docs, architecture lifecycle, real launch smoke |

Documentation tests should assert entrypoints and architectural invariants. Do
not freeze entire paragraphs or require cosmetic wording.

## Development Setup

From the authored checkout:

```bash
npm ci
python3 scripts/install_env.py \
  --package-root . \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

Use the package runtime wrapper for Python tests when the host interpreter does
not contain the declared environment:

```bash
python3 scripts/ts_runtime.py run -m pytest -q
```

Do not install project dependencies into a shared Conda base environment. Keep
credentials, sessions, caches, workspaces, release archives, and generated
reports out of tracked source files.

## Validation Tiers

Run the narrowest relevant test first, then the shared gates for a public or
cross-module change.

### Documentation or Skill change

```bash
python3 -m pytest -q tests/test_readme_contract.py tests/test_decision_templates.py
python3 scripts/check_package.py
git diff --check
```

Also run the Skill validator against
`skills/transition-state-workflow/` when available.

### Python contract or kernel change

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
```

### Pi extension or Agent runtime change

```bash
npm run typecheck
npm run test:pi-adapter
```

The recording-provider suite must cover the real public inventory, child tool
isolation, provider failure propagation, schema repair, journals, and UI
lifecycle without contacting a production model endpoint.

### Package and release change

```bash
npm run test:package
npm pack --dry-run --json
python3 scripts/check_package.py
python3 scripts/build_release.py --output-dir dist --json
```

Release build requires a clean checkout. For a dirty local smoke only, use
`--allow-dirty` and never distribute that output.

## Version Changes

The package version is currently duplicated in maintained validation and UI
metadata. A version bump must update and test at least:

- `package.json` and `package-lock.json`;
- `extensions/shared/package-profile.ts`;
- `scripts/check_package.py`;
- version-specific tests and release fixtures.

Do not change a schema version merely because the package version changed.
Schema versions change only when their data contract changes.

## Release Procedure

1. Inspect `git status` and preserve unrelated user changes.
2. Run focused tests, full pytest, TypeScript typecheck, Pi adapter tests, and
   package checks.
3. Confirm documentation and examples match the active schemas and tools.
4. Commit the intended source changes.
5. Build the release from the clean commit.
6. Record release ID, source commit, archive path, size, and SHA-256.
7. Install into a staging or target TSPi root with `install_release.py`.
8. Install/resolve the selected Python runtime.
9. Verify `TSPi --help`, a workspace bootstrap, tool inventory, and optional
   remote status without submitting a real job.
10. Restart user sessions only in an authorized maintenance window.

The installer atomically selects `current`; processes already running retain
their original release. Installing a release does not modify workspaces or
remote jobs.

## Rollback Discipline

Preserve each distributed archive and manifest. Roll back by running the same
installer against the previous pair, resolving its Python runtime, and starting
a new TSPi process. Do not edit installed files or use Git operations inside a
release directory.

Rollback does not undo v3 Decisions or downgrade workspace state. If a release
introduced an incompatible schema mutation, recovery requires a separately
designed forward migration, not a package pointer switch.

## Review Before Handoff

Check the patch as if it came from another contributor:

- Does every changed rule have one clear owner?
- Do docs, CLI help, tool schemas, tests, and runtime behavior agree?
- Did any old phase, Node type, Evidence role/layer, hypothesis field, or tool
  alias return to a normal v3 surface?
- Can a new installer start and resume a workspace from the documentation?
- Can a Root Agent identify which calls reason, mutate, execute, or only render?
- Are crash, ambiguity, and delivery limits stated rather than hidden?
- Were unrelated working-tree changes left untouched?
- Is every claimed validation backed by an actual completed command?
