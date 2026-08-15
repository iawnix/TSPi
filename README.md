# @iawnix/ts-agent

`@iawnix/ts-agent` is the Pi package maintained in the TSAgentSkill
repository. It supports evidence-driven transition-state research with one
Root Agent, a deterministic scientific workspace, bounded Review and operator
sessions, typed local or SSH/Torque calculations, reporting, notifications,
and a read-only activity UI.

This branch supports Pi Agent only. Python modules are deterministic kernels
called by the Pi extensions; they are not a second Agent runtime. Supported Pi
versions are `>=0.81.1 <1.0.0`, with the exact tested SDK versions pinned in
`package.json`.

## Core Boundary

```text
Root Agent chooses the research path and scientific interpretation
  -> Workspace Kernel validates and commits scientific state
  -> Review advises; bounded operators execute selected actions
  -> UI projects activity without gaining authority
```

The long-lived scientific vocabulary is intentionally small:

- **Node**: one bounded research act with parent topology and descriptive tags.
- **Claim**: one versioned scientific statement authored by the Root Agent.
- **Evidence**: immutable facts, source artifacts, and provenance.
- **Gate**: one deterministic fact-policy result used by declared acceptance
  policies.

There is no workflow phase, stage, Node type, Evidence role, or Evidence layer
that selects the next action. Tags are for display and search only. Program
completion, scheduler state, Review output, and operator success are not
scientific support by themselves.

New state uses `ts-decision/3` and `ts-node/3`. Runtime reads and writes v3 only;
v2 workspaces require the explicit copy migration.

## Documentation

- [Installation and Operations](docs/INSTALLATION.md): prerequisites, release
  install, configuration, startup, resume, upgrade, rollback, and recovery.
- [Architecture](docs/ARCHITECTURE.md): component ownership, Agent and operator
  lifecycles, persistence, result delivery, and extension inventory.
- [Maintainer Guide](docs/MAINTAINER_GUIDE.md): source setup, contract changes,
  tests, release procedure, and documentation ownership.
- [Root Skill](skills/transition-state-workflow/SKILL.md): the operating policy
  loaded into research sessions, with focused scientific and tool references.

These three documents are shipped in the validated release. Runtime package
code and public operating material are immutable; maintenance still happens
only in the authored Git checkout. `TSPi` never loads that checkout directly.

## Quick Install

Build a content-addressed archive from a clean authored checkout and install it
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

The installer verifies archive identity, size, SHA-256, safe members, required
files, and immutable release permissions before atomically selecting
`.pi/packages/ts-agent/current`. It installs the launcher as:

```text
<installation>/TSPi -> .pi/packages/ts-agent/current/TSPi
```

Configure Pi authentication and model selection separately. Set `PI_BIN` when
Pi is not installed at the launcher's default location. Remote execution and
email notifications are optional installation-owned configuration; see the
installation guide.

## Start TSPi

No workspace directory must be created manually. The launcher creates or
validates it under `<installation>/workspaces/`:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a --continue
./TSPi --workspace reaction-a --phone
./TSPi --check-remote
```

One nonblocking lock permits one Root Agent process per workspace. Different
workspace names can run concurrently. Terminal mode starts a new Pi session
unless normal Pi arguments such as `--continue` are supplied; Phone mode always
attaches with `--continue`.

Startup validates the active release and installation configuration, prepares
workspace-local Pi session state, acquires the Root lock, and performs
deterministic workspace bootstrap. Fresh workspaces are initialized once;
complete v3 workspaces are only validated; partial, invalid, or v2 workspaces
fail closed. Ordinary startup does not contact the remote scheduler.

## Public Surface

Pi loads one Skill, five extensions, one theme, eleven tools, and four slash
commands. Tool prefixes describe execution authority:

- `ts_workspace_*`: deterministic context, draft, validation, and canonical
  apply. Only `ts_workspace_decision_apply` writes scientific state.
- `ts_subagent_review`: one fresh advisory scientific Review.
- `ts_subagent_compute`, `ts_subagent_render`, and `ts_subagent_report`: fresh,
  request-scoped operator sessions. They execute a Root-selected action and
  cannot decide Claims or Gates.
- `ts_remote_inspect`: deterministic read-only SSH/Torque diagnostics.
- `ts_review_disposition`: deterministic write-once Root response to Review.
- `ts_notify_user`: deterministic delivery to the fixed installation target.

The slash commands are `/ts-context`, `/ts-validate`, `/ts-remote`, and
`/ts-subagent-history`. The last command merges transient activity with durable
run journals in a paginated read-only browser.

## Research Loop

The Root Agent normally:

1. Reads compact context and identifies one unresolved question.
2. Drafts, validates, and applies a `start_node` Decision.
3. Creates or cites Claims and selects a scientifically justified method.
4. Links immutable operations, verifies local artifacts, and registers facts.
5. Evaluates only the Gates required by the Claim or acceptance policy.
6. Closes the Node with explicit Claim updates, limitations, and optional audit.
7. Re-reads context and independently chooses another Node, stop, or completion.

Gaussian is a first-class candidate generator when scans, QST, or direct TS
optimization are justified. The adapter catalog is not a method priority list.
A candidate, converged program, or single imaginary frequency is not an
accepted TS. `accepted-ts/2` requires passing target-compatible TS/Freq and
connectivity Gates; Claims may require additional Gates.

## Compute And Remote

Preparation accepts `ts-calculation-request/1`, resolves logical `artifactId`
plus `inputRole` bindings, and writes an immutable
`ts-calculation-intent/3`. Supported adapter tasks currently include:

- Gaussian: `sp`, `opt`, `freq`, `opt_freq`, `irc`;
- xTB: `sp`, `opt`, `freq`, `opt_freq`, `scan`, `md`;
- CREST: `conformer_search`;
- ASE: `neb`;
- QBICS: `dmecp`.

Capability means the adapter can express and validate a task, not that software,
storage, SSH, or Torque is healthy. Remote jobs are isolated by workspace ID,
Node, and intent under the configured remote root. Transfer failures before a
scheduler effect are retryable only when the typed result says so. Ambiguous
submit or cancel effects must be reconciled, never replayed. Collection uses
the immutable artifact manifest and does not depend on scheduler history.

## State And Reports

Canonical scientific files are limited to the v3 workspace registries, Node
records, accepted artifacts, Decisions, and transaction logs. Calculation
attempts, remote receipts, Review/operator journals, notifications, reports,
sessions, and UI state are operational or derived data.

Report packages are built atomically from a valid workspace. Their manifest
binds the source scientific revision and every output file by SHA-256. Review
and operator results become scientifically usable only after the Root Agent
verifies primary artifacts and registers normal Evidence through a Decision.

## Validation

Run validation from the authored checkout, not an installed release:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run typecheck
npm run test:pi-adapter
npm run test:package
npm pack --dry-run --json
git diff --check
```
