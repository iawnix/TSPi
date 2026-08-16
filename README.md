# @iawnix/ts-agent

`@iawnix/ts-agent` is a Pi package for auditable transition-state research. It
combines one strategy-owning Root Agent with a deterministic research kernel,
typed local or SSH/Torque calculations, semantic scientific observations,
declarative validation, reproducible reports, optional notifications, and a
read-only activity UI.

This `ts-dag` branch is protocol v4. It intentionally has no v2/v3 reader,
migrator, field alias, or runtime compatibility path. A legacy study must keep
using its matching release or start a new v4 workspace.

## Core Boundary

```text
Root Agent
  chooses questions, hypotheses, methods, alternatives, backtracking, and stop
        |
        v
Research Kernel
  Claim graph + ResearchAct DAG + immutable Observations + Findings
        |
        +-- deterministic Compute / Render / Report
        +-- declarative Validation Engine
        +-- graph Context Compiler
        +-- isolated advisory Review Agent
```

Only the Research Kernel mutates canonical scientific state. The Root Agent
selects what to investigate but does not choose paths, filenames, record IDs,
or validation verdicts. Review is the only child model session. Compute,
Render, Report, remote inspection, notifications, and workspace control are
deterministic host tools.

The long-lived scientific vocabulary is:

- **Claim**: one explicit, versioned scientific statement.
- **ClaimRelation**: a directed dependency, refinement, conflict, or alternative
  relation between Claims. Relations form a DAG but do not route execution.
- **ResearchAct**: one bounded research act with zero or more dependencies.
  Dependency edges form the exploration DAG and support branching, merging,
  and backtracking without rewriting history.
- **Observation**: one immutable semantic value, concept, subject, artifacts,
  and provenance record.
- **Finding**: one explicit anomaly, limitation, conflict, or unresolved
  question, including acceptance-blocking findings.
- **GateSpec / ValidationResult**: a frozen declarative validation definition
  and its deterministic result over selected Observations.

There is no workflow phase, stage, Node type, Evidence role/layer, fixed Gate
router, or hard-coded research sequence. Tags and relation labels are metadata;
they never authorize a next action.

## Why This Package

A general model can propose a transition-state search plan. This package adds
the controls needed to make a long scientific campaign inspectable and
reproducible:

- canonical Claims, alternatives, hypotheses, failures, and backtracking;
- immutable artifact and Observation provenance;
- deterministic local and remote effects with explicit ambiguity handling;
- validation standards frozen before evaluation and bound by digests;
- acceptance records that snapshot the Claim, specifications, results, and
  unresolved Findings;
- bounded context projections instead of repeatedly dumping the workspace;
- independent Review whose advice cannot silently change scientific state.

## Documentation

- [Installation and Operations](docs/INSTALLATION.md): release installation,
  runtime configuration, workspace startup, upgrade, rollback, and recovery.
- [Architecture](docs/ARCHITECTURE.md): component ownership, state model,
  lifecycle, persistence, validation, context, and result delivery.
- [Maintainer Guide](docs/MAINTAINER_GUIDE.md): source layout, contract-change
  rules, tests, release discipline, and documentation ownership.
- [ADR 0001](docs/adr/0001-dag-research-kernel-v4.md): the incompatible v4 DAG
  and declarative-validation decision.
- [Root Skill](skills/transition-state-workflow/SKILL.md): concise operating
  policy loaded into each TSPi research session.

## Quick Install

Build a content-addressed release from a clean authored checkout and install it
into a dedicated TSPi root:

```bash
python3 scripts/check_package.py
python3 scripts/build_release.py --output-dir dist --json
python3 scripts/install_release.py \
  --manifest dist/ts-agent-release.json \
  --install-root /path/to/TSPi-installation \
  --json

export TS_AGENT_SKILL_ROOT=/path/to/TSPi-installation/.pi/packages/ts-agent/current
python3 "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --runtime-home /path/to/TSPi-installation/.agents/runtime/transition-state-workflow \
  --env-root /path/to/TSPi-installation/.agents/envs/transition-state-workflow \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

The release installer verifies package identity, archive size, SHA-256, safe
members, required files, and immutable permissions before atomically selecting
`.pi/packages/ts-agent/current`. It installs:

```text
<installation>/TSPi -> .pi/packages/ts-agent/current/TSPi
```

Pi model authentication, SSH/Torque access, and notifications are
installation-owned configuration and are not stored in a research workspace.

## Start TSPi

The launcher creates and bootstraps a workspace under
`<installation>/workspaces/`; the user does not create it first:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a --continue
./TSPi --workspace reaction-a --phone
./TSPi --check-remote
```

One nonblocking lock permits one Root Agent process per workspace. Different
workspace names can run concurrently. Normal terminal mode starts a new Pi
conversation unless Pi's `--continue` is supplied; Phone mode resumes the
workspace conversation automatically.

Bootstrap is idempotent for a complete v4 workspace: fresh state is created
once, valid state is checked without canonical rewrites, and partial, invalid,
or legacy canonical state fails closed. Ordinary startup does not contact the
remote scheduler.

## Public Surface

Pi loads one Skill, five extensions, one theme, twelve public tools, and four
slash commands:

- `ts_workspace_context`: bounded graph, artifact, compute-capability, or
  validation-capability projection.
- `ts_workspace_decision_draft`, `ts_workspace_decision_validate`, and
  `ts_workspace_decision_apply`: the only canonical mutation pipeline.
- `ts_subagent_review`: one isolated advisory Review of a target Claim, with an
  optional one-batch logical-artifact reader instead of preloaded file content.
- `ts_review_disposition`: one deterministic Root response to a completed
  Review.
- `ts_compute`: deterministic prepare, submit, inspect, collect, cancel, and
  parse operations.
- `ts_artifact_import`: bounded, Act-owned bootstrap import for Gaussian, XYZ,
  or xTB control inputs; the host allocates path, filename, digest, and ID.
- `ts_render`: deterministic local render, comparison, animation, or mechanism
  visualization.
- `ts_report`: deterministic atomic report-package build.
- `ts_remote_inspect`: read-only SSH/Torque diagnostics.
- `ts_notify_user`: fixed-target, receipt-bound notification delivery.

The slash commands are `/ts-context`, `/ts-validate`, `/ts-remote`, and
`/ts-subagent-history`. The history browser shows Review runs only; deterministic
tool activity is shown through normal tool entries and the unified TS Activity
projection.

## Research Loop

The Root Agent normally:

1. Reads the frontier or delta context and states one unresolved question.
2. Creates or updates Claims and starts a bounded ResearchAct with explicit
   dependencies and falsifiers.
3. Selects a scientifically justified method and invokes deterministic tools.
4. Verifies local primary artifacts and records semantic Observations.
5. Records anomalies and unresolved limits as Findings.
6. Freezes relevant GateSpecs before evaluation, then evaluates them over
   explicitly selected Observations.
7. Updates Claim status, completes the ResearchAct, and accepts a Claim only
   when a named profile passes.
8. Recompiles context and independently chooses a branch, merge, backtrack,
   new question, explicit stop, or completion.

The DAG records what happened; it does not prescribe what must happen next.
Gaussian is a first-class candidate-generation option when scans, QST, or
direct TS optimization are justified. The adapter catalog is not a method
priority list. A converged program, candidate geometry, or isolated imaginary
frequency is never an accepted TS by itself.

An empty workspace is not a compute dead end. Start an open ResearchAct, import
the first bounded seed with `ts_artifact_import`, resolve its logical `art_*`
record, and then prepare Compute. Imported text never grants path authority.

## Compute And Remote

Preparation accepts `ts-calculation-request/2`, resolves logical `artifactId`
plus `inputRole` bindings, and writes an immutable
`ts-calculation-intent/4` under the owning Act. Supported adapter tasks include:

- Gaussian: `sp`, `opt`, `freq`, `opt_freq`, `irc`;
- xTB: `sp`, `opt`, `freq`, `opt_freq`, `scan`, `md`;
- CREST: `conformer_search`;
- ASE: `neb`;
- QBICS: `dmecp`.

Capability means an adapter can express and validate a task; it does not prove
that software, storage, SSH, Torque, or a queue is healthy. Remote jobs are
isolated by workspace ID, Act, and immutable intent. Pre-effect failures may be
retryable. Ambiguous submit or cancel effects must be reconciled and must never
be blindly replayed. Collection is manifest-driven and does not depend on
scheduler history.

## Validation And Acceptance

Validation is data-driven:

```text
versioned template + parameters
  -> fully expanded frozen GateSpec
  -> registered deterministic predicates
  -> immutable ValidationResult
```

The Root Agent may select a packaged template or compose a definition from
registered predicates. It cannot inject Python, shell, imports, or arbitrary
expressions. Built-in templates cover common classical TS, reaction-coordinate,
connectivity, identity, electronic-structure, state-character, robustness,
thermochemistry, and pathway checks. New scientific domains extend this
mechanism with maintained templates and predicates instead of adding workflow
branches.

Acceptance is separate from Claim status. A supported Claim needs at least one
attached GateSpec. A profile verifies required dimensions, the latest passing
result for every attached GateSpec, current digests, and the absence of
unresolved blocking Findings, then writes an immutable historical record.
That record is current only while its Claim, attached specifications, latest
results, profile, and relevant Finding snapshot still match. Later research
does not erase history; it makes the old record stale until a new assessment is
recorded.

## State And Reports

Canonical scientific state consists of v4 graph registries, frozen validation,
acceptance snapshots, Decisions, and transaction logs. Calculation attempts,
remote controls, Review journals, notifications, reports, Pi sessions, and UI
activity are operational or derived state.

Report packages are built atomically from a valid workspace. Their manifest
binds the source scientific revision and every output file by SHA-256. Review
advice and deterministic tool results become scientific support only after the
Root Agent verifies primary artifacts and records normal Observations through a
Decision.

## Validation

Run validation from the authored checkout, not an installed release:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run typecheck
npm run test:pi-adapter
python3 scripts/check_package.py
NPM_CONFIG_CACHE=/tmp/ts-agent-npm-cache npm pack --dry-run --json
git diff --check
```
