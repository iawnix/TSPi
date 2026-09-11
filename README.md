# TSPi Package

[English](README.md) | [简体中文](README.zh-CN.md)

This repository owns the required `@iawnix/ts-agent` component, the
independently packaged read-only Web component, and the assembler for TSPi
Packages. TS Phone remains an independently maintained source repository. Each
distributed release binds the required Agent and any selected Web or Phone
component into one content-addressed component set with one `current` pointer.

The Agent combines one strategy-owning Root Agent with a deterministic research kernel,
typed SSH/Torque calculations with deterministic local preparation and parsing,
semantic scientific observations,
declarative validation, reproducible reports, optional notifications, a
session-scoped activity UI, and a read-only multi-workspace research explorer.

This release line implements one workspace contract centered on
ResearchPhase, ResearchNode, and Claim. Unsupported layouts fail closed instead
of being rewritten during startup.

## Core Boundary

```text
Root Agent
  chooses questions, hypotheses, methods, alternatives, backtracking, and stop
        |
        v
Research Kernel
  ResearchPhase roadmap + ResearchNode DAG + Claim graph
  parser candidates + immutable Observations + Findings + frozen ProofSpecs
        |
        +-- deterministic compute kernel / Render / Report
        +-- declarative Validation Engine
        +-- graph Context Compiler
        +-- isolated operational Compute Agent
        +-- isolated advisory Review Agent
```

Only the Research Kernel mutates canonical scientific state. The Root Agent
selects what to investigate but does not choose paths, filenames, record IDs,
or validation verdicts. Compute and Review use isolated child model sessions.
Compute may only execute a fixed host-bound action plan; it cannot choose a
method or create scientific meaning. Render, Report, remote inspection,
notifications, workspace control, and every underlying compute action remain
deterministic host tools.

The long-lived scientific vocabulary is:

- **ResearchPhase**: a human-readable roadmap group with a title and objective.
  It organizes Nodes for navigation but has no lifecycle or policy authority.
- **Claim**: one explicit, versioned scientific statement.
- **ClaimRelation**: a directed dependency, refinement, conflict, or alternative
  relation between Claims. Relations form a DAG but do not route execution.
- **ResearchNode**: one user-visible research decision episode: why one bounded
  question is next, what principal result will answer it, and what changed.
  Dependencies support continuation, branching, merging, and backtracking.
- **Observation**: one immutable semantic value, concept, subject, artifacts,
  and provenance record.
- **Finding**: one explicit anomaly, limitation, conflict, or unresolved
  question, including acceptance-blocking findings.
- **ProofSpec / ValidationResult**: a frozen declarative validation definition
  and its deterministic result over selected Observations.

There is no prescribed research sequence or automatic next-action policy.
ResearchPhase, tags, and relation
labels are navigation or scientific metadata; they never authorize a next
action.

## Why This Package

A general model can propose a transition-state search plan. This package adds
the controls needed to make a long scientific campaign inspectable and
reproducible:

- canonical Claims, alternatives, hypotheses, failures, and backtracking;
- immutable artifact and Observation provenance;
- deterministic local preparation/parsing and remote effects with explicit
  ambiguity handling;
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
- [ADR 0001](docs/adr/0001-phase-node-research-kernel.md): the Phase +
  ResearchNode kernel and declarative-validation decision.
- [ADR 0002](docs/adr/0002-repository-and-component-boundaries.md): TSPi core,
  optional Phone/Web components, protocol ownership, repository topology, and
  implementation sequence.
- [Root Skill](skills/tspi-orchestration/SKILL.md): concise operating
  policy loaded into each TSPi research session.
- [Public Glossary](skills/tspi-orchestration/references/glossary.md):
  stable research, execution, and Review terminology.
- [Skill Catalog](skills/README.md): orchestration, search-method, xTB, Gaussian,
  QBICS, connectivity, rendering, reporting, and email Skills with their
  loading boundaries.

## Skill Family

The package exposes one orchestration Skill, five scientific-method Skills, and
three output/delivery Skills. The orchestration Skill owns cross-cutting
contracts and task management; focused Skills are loaded when a question needs
their method or delivery capability.

| Skill | Scope |
| --- | --- |
| `tspi-orchestration` | workspace, Decision, evidence, validation, subagents, and recovery contracts |
| `tspi-transition-state-search` | candidate construction and transition-state search strategy |
| `tspi-xtb` | xTB and CREST calculations and result interpretation |
| `tspi-gaussian` | Gaussian input and output validation |
| `tspi-qbics` | QBICS/DMECP electronic-state crossings |
| `tspi-connectivity` | reaction-path endpoints and molecular structure identity |
| `tspi-render` | deterministic visual artifacts |
| `tspi-report` | evidence-bound report packages |
| `tspi-email` | fixed-target notification delivery |

## Repository Layout

The source tree follows ownership boundaries rather than language names:

| Path | Responsibility |
| --- | --- |
| `contracts/` | Versioned Phone, Web, and component-release contracts |
| `packages/ts-agent-kernel/ts_agent/` | Python Research Kernel and deterministic scientific services |
| `packages/ts-agent-runtime/` | Reusable Agent, Compute, Review, and artifact runtime modules |
| `components/ts-web/` | Independent optional Web client, provider client, server, and static UI |
| `apps/` | Host and Terminal process entrypoints |
| `extensions/` | Pi extensions and Phone adapter policy |
| `skills/` | Public model-facing Skill and focused references |
| `scripts/` | Stable compatibility entrypoints and thin wrappers |
| `tools/` | Contract synchronization, checks, and developer tooling |
| `docs/` | Architecture, operations, maintenance, and ADRs |

`cluster_mcp` is retired and absent from the repository. `build/`, `dist/`,
`.runtime/`, and other caches are generated locally and excluded from source
and release boundaries. The Python import namespace remains `ts_agent` even
though its authored source now lives under the named kernel package directory.
The Agent-side `scripts/ts_web_provider.py` is the TSPi-owned provider entrypoint;
the Web component calls it through the versioned provider protocol.

## Quick Install

Build and install the required Agent with the default Web component from a
clean TSPi checkout:

```bash
cd /path/to/TSPi
python3 scripts/build_package.py \
  --output-dir dist/package \
  --json
python3 scripts/install_package.py \
  --manifest dist/package/tspi-package-release.json \
  --install-root /path/to/TSPi-installation \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

To add the optional Phone component, first build a validated release from the
independent `ts-phone` checkout, then pass its manifest to the TSPi assembler:

```bash
cd /path/to/ts-phone
npm ci
apps/mobile/tool/build_release_android.sh
python3 deploy/build-component-release.py \
  --output-dir dist/component \
  --json

cd /path/to/TSPi
export TSPI_ANDROID_BUILD_TOOLS=/path/to/android-sdk/build-tools/<version>
python3 scripts/build_package.py \
  --phone-manifest /path/to/ts-phone/dist/component/ts-phone-component-release.json \
  --output-dir dist/package \
  --json
```

Pass `--without-web` when a Core-only Package is required. End users receiving
a prebuilt Package archive and manifest can skip the component build steps.

The suite builder internally creates the Agent component and its
`ts-agent-kernel` wheel, then binds any selected optional components to that
archive. The builder and installer independently verify each selected
component's contracts, including the Phone APK signer, package metadata,
embedded source snapshot, and build attestation. They also verify the outer
Package, every declared nested archive, protocol compatibility, wheel
descriptors, safe members, required files, and immutable permissions. The
installer then prepares and probes the target release's Python runtime before
atomically selecting `.pi/packages/tspi/current`. An invalid runtime cannot
activate a release. The installer creates stable entrypoints only for the
selected components:

```text
<installation>/TSPi          -> .pi/packages/tspi/current/agent/TSPi       (always)
<installation>/TSWeb         -> .pi/packages/tspi/current/web/bin/ts-web     (Web)
<installation>/TSPhoneCtl    -> .pi/packages/tspi/current/agent/TSPi       (Phone)
<installation>/TSPhoneServer -> .pi/packages/tspi/current/agent/TSPi       (Phone)
```

Installation selects content only. It does not start or restart TS Phone and
does not install the bundled APK onto a device.
The shared launcher reads installation `.pi/ts-phone/server.env` as data and
dispatches to the selected Phone component. The installer supplies an
installation-scoped `.pi/ts-phone/ts-phone.service` template without registering it.

The managed runtime separates a shared, environment-spec-addressed Conda base
containing NumPy, RDKit, SciPy, and optional `xyzrender` from a
payload-addressed venv containing only the exact release's `ts-agent-kernel`
wheel. TSPi will not combine a selected Pi release with stale Python modules
from another release.

Pi model authentication, SSH/Torque access, and notifications are
installation-owned configuration and are not stored in a research workspace.

## Start TSPi

Start the configured Host (`TSPhoneServer`), then open a terminal client.
Projects live under `<installation>/workspaces/`:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a --continue
./TSPi --workspace reaction-a --phone
./TSPi --check-remote
```

Terminal and Phone share a Host-managed Worker and its original Pi history.
Opening a conversation reads history only; sending a message or `/continue`
starts an offline Worker. Terminal exit detaches without stopping research.
`--phone` is an alias for this shared connection. `--session-id <id>` selects
an exact conversation; `-c` selects the latest when no Controller is live.
With no workspace argument, the terminal opens the project selector.
New projects require confirmation. See [Terminal](docs/TERMINAL.md).

Only a Worker owns the research/session writer locks. Multiple attached UIs
do not acquire them. Different workspaces can run concurrently. An explicit
`--standalone` starts native Pi instead, preserving its exclusive writer guards.

When the TS Phone Host is configured with this installation's `TSPi`
entrypoint, the app can create projects and independent conversations. Its
**Continue research** action starts or rejoins the original session without an
open terminal; browsing history starts nothing. **Read-only assistant** is an
explicit alternative. Switching an idle Host-owned runtime needs confirmation;
a busy or external CLI is never stopped automatically. The Host's `--phone-worker` and
`--lifecycle-preflight` flags are private integration operations, not user CLI
commands. A Worker controller acquires the same Root Agent lock and may
bootstrap the workspace; an observer is strictly read-only and requires an
existing workspace. The Host keeps display names and archive/trash state in its
own owner-only `management.json`. It does not add those fields to scientific
workspace state.

For a native read-only assistant use `--standalone --phone --phone-access observer` with a
different session. Lock contention does not silently downgrade permissions.
In-process new/resume/fork is blocked in native guarded Pi; exit and reopen instead.

Bootstrap is idempotent for a complete workspace: fresh state is created once,
valid state is checked without canonical rewrites, and partial, invalid, or
unsupported canonical state fails closed. Ordinary startup does not contact the
remote scheduler.

## Explore Workspaces

The packaged `ts_web` server gives users a Node-first Research Map without
changing research state. Its default view groups each Phase into a shared
foundation and Claim-owned hypothesis lanes. Node rows expose the bounded
objective, upstream Evidence dependencies, Attempt count, and latest
calculation state. Structured `reaction_path.endpoint_assignment` Observations
appear as deduplicated connectivity evidence inside the owning lane; this
display does not imply that a connectivity ProofSpec passed, and the Web does not
infer reaction direction from endpoint names. The exact cross-Phase
ResearchNode dependency DAG remains available as the secondary audit mode with
pan, zoom, fit, branch, merge, and backtracking lineage.

Opening a Node exposes a compact run summary in Overview and a dedicated Runs
tab with Attempt-family filters, fixed pagination, purpose,
retry/recalculation lineage, method, parameters, job state, and bound Compute
runs; Attempts never become peer roadmap Nodes. Claims, validation, Findings,
operational activity, and files stay in separate views. Scientific Conclusions
provides Table and Map modes over the same Claims; the interactive Claim Map
does not duplicate either Research Map mode.

```bash
/path/to/TSPi-installation/TSWeb serve \
  --state-dir /path/to/TSPi-installation/.pi/ts-web \
  --source-root /path/to/TSPi-installation/workspaces/reaction-a \
  --label "Reaction A" \
  --host 127.0.0.1 \
  --port 8766
```

Repeat `--source-root` and `--label` to register several workspaces. The Web
registry must remain outside every source workspace. The server has no login;
use `--host 0.0.0.0` only on a trusted, firewalled LAN. See
[Installation and Operations](docs/INSTALLATION.md#run-the-research-explorer)
for registration and exposure details.

With the standard `<installation>/.pi/ts-web` state directory, the explorer
also treats `<installation>/workspaces` as a managed discovery root. At startup
and each catalog refresh it adds direct workspace children and removes rows
whose managed source directory or `workspace.json` has disappeared. A missing
or unreadable discovery root is left untouched, and manually registered roots
outside the managed directory are never pruned. Use `--workspace-root` to
declare a different managed root.

While the page is visible, it checks the selected workspace every five seconds.
An unchanged check returns only revision identities; a changed check replaces
the View and Graph together while preserving the current view, scroll position,
and open inspector. A transient refresh failure keeps the last valid snapshot
and marks it stale.

Starting through the stable `TSWeb` entrypoint also enables release hot restart.
After an atomic `current` switch and managed-runtime refresh, the server closes
its listening socket and executes the same stable command under the new release.
Use `--no-watch-release` only for diagnostics. This is an orderly short restart,
not in-process module reload or zero-downtime socket handoff.

## Public Surface

Pi registers nine Skills, five extensions, one theme, twelve public tools, and
four slash commands. Skill bodies are loaded on demand after the matching
domain is identified.

- `ts_state`: bounded graph, artifact, compute-capability, or proof-capability
  projection.
- `ts_change`: the only canonical mutation entrypoint. The kernel privately
  compiles, dry-runs, and atomically commits one Root-authored change under one
  workspace lock.
- `ts_review`: one isolated advisory Review of a target Claim, with an
  optional one-batch logical-artifact reader instead of preloaded file content.
- `ts_reply`: one deterministic Root response to a completed
  Review.
- `ts_calc`: one isolated operational lifecycle: `launch`
  (`prepare -> submit`), `inspect` (`status -> optional tail`), `finalize`
  (`collect -> parse`), or `cancel`. Every action is a zero-argument tool bound
  by the host to one immutable intent.
- `ts_seed`: deterministic RDKit ETKDGv3 seed generation from one
  connected SMILES, with content-addressed XYZ and provenance.
- `ts_compare`: deterministic atom-mapped XYZ comparison with a
  Node-owned, content-addressed JSON analysis.
- `ts_import`: bounded, Node-owned bootstrap import for Gaussian, XYZ,
  or xTB control inputs; the host allocates path, filename, digest, and ID.
- `ts_render`: deterministic local render, comparison, animation, or an ordered
  reactant/transition-state/product mechanism visualization.
- `ts_report`: deterministic atomic report-package build.
- `ts_remote`: read-only SSH/Torque diagnostics.
- `ts_notify`: configured-target, receipt-bound notification delivery.

The slash commands are `/ts`, `/ts-check`, `/ts-remote`, and `/ts-runs`.
The run browser shows durable Compute and Review
runs; deterministic tool activity is shown through normal tool entries and the
unified TS Activity projection. TS Activity is a transient live view of kind,
owner, action, state, and elapsed time. History uses canonical `sub_n` run IDs;
its detail view leads with outcome or error and keeps journal paths under Audit.

## Research Loop

The Root Agent normally:

1. Reads the frontier or delta context and states one unresolved question.
2. Creates or reuses a navigation Phase and starts one decision-sized
   ResearchNode with explicit dependencies and Claim scope.
3. Selects a scientifically justified capability and invokes bounded tools.
4. Inspects parser-produced ObservationCandidates, verifies their primary
   artifacts, and promotes selected values into semantic Observations with
   `ts_change`.
5. Records anomalies and unresolved limits as Findings.
6. Freezes relevant ProofSpecs before evaluation, then evaluates them over
   explicitly selected Observations.
7. Updates Claim status and completes the ResearchNode as soon as its one
   question is answered.
8. Recompiles context and records the next material decision as a dependent
   Node or new Phase, or explicitly stops. Acceptance still requires a passing
   named profile.

A changed question, principal deliverable, hypothesis scope, independent method
branch, backtrack, or synthesis goal requires a new Node. Same-question retries
and method variations remain retry or recalculation Attempts. One canonical
Decision may open at most one Node, while a transition
may atomically close the current Node and open one explicitly dependent
successor. It may also start and complete the same purely analytical Node.
Registry updates and tool calls remain internal Node History rather than
roadmap Nodes.

The DAG records what happened; it does not prescribe what must happen next.
Gaussian is a first-class candidate-generation option when scans, QST, or
direct TS optimization are justified. The adapter catalog is not a method
priority list. A converged program, candidate geometry, or isolated imaginary
frequency is never an accepted TS by itself.

An empty workspace is not a compute dead end. Start an open ResearchNode. Use
`ts_seed` for a single-molecule SMILES or `ts_import` for
existing Gaussian, XYZ, or xTB control text, then pass the returned logical
`art_*` to Compute. Neither tool grants path authority or scientific validity.
Use `ts_compare` for deterministic RMSD, reaction-center, internal
coordinate, or explicit stereochemical checks between two registered XYZ
artifacts. Its output remains operational until selected facts are registered
as Observations through `ts_change`.

## Compute And Remote

Preparation accepts `ts-calculation-request/5`, resolves logical `artifactId`
plus `inputRole` bindings, and writes an immutable
`ts-calculation-intent/7` under the owning Node. The intent binds the stable Node
contract, a digest of capability parameters and input artifacts, and explicit
same-Node retry or recalculation lineage. Supported capabilities include:

- Gaussian: `sp`, `opt`, `freq`, `opt_freq`, `irc`;
- xTB: `sp`, `opt`, `freq`, `opt_freq`, `scan`, `md`;
- CREST: `conformer_search`;
- ASE: `neb`;
- QBICS: `dmecp`.

Capability means an adapter can express and validate a task; it does not prove
that software, storage, SSH, Torque, or a queue is healthy. A `local` execution
target is intentionally limited to dry-run preparation and parsing of outputs
that already exist in the workspace; it does not start a local Gaussian/xTB
process. Use a configured `remote` target for submit, status, tail, collect, or
cancel. Remote jobs are
isolated by workspace ID, Node, and immutable intent. Pre-effect failures may be
retryable and are reported separately from unresolved controls. They do not
require reconciliation or block Node completion. Ambiguous submit or cancel
effects must be reconciled and must never be blindly replayed. Collection is
manifest-driven and does not depend on scheduler history.

The Root supplies the scientific request to `ts_calc`. Before the
child starts, the host creates or resolves the intent, verifies its digest, and
binds the exact action tools. The child receives no Root transcript, Skill,
filesystem, shell, arbitrary arguments, or recursive delegation. Its result
tool accepts only a summary and limitations; outcome, program state, artifacts,
facts, provenance, and reconciliation state are derived from journaled typed
actions. These operational records are not Observations until Root verifies the
primary artifacts and promotes selected parser candidates through `ts_change`.

## Validation And Acceptance

Validation is data-driven:

```text
versioned template + parameters
  -> fully expanded frozen ProofSpec
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
attached ProofSpec. A profile verifies required dimensions, the latest passing
result for every attached ProofSpec, current digests, and the absence of
unresolved blocking Findings, then writes an immutable historical record.
That record is current only while its Claim, attached specifications, latest
results, profile, and relevant Finding snapshot still match. Later research
does not erase history; it makes the old record stale until a new assessment is
recorded.

## State And Reports

Canonical scientific state consists of Phase, Node, and Claim registries,
frozen ProofSpecs and ValidationResults,
acceptance snapshots, Decisions, and transaction logs. Calculation attempts,
remote controls, Compute/Review journals, notifications, reports, Pi sessions, and UI
activity are operational or derived state.

Report packages are built atomically from a valid workspace. Their manifest
binds the source scientific revision and every output file by SHA-256. Logical
PNG/GIF artifacts can be copied into a package `assets/` directory before
notification; Notify accepts only unchanged manifest members. Compute runs live
under their `calc_n` Attempt, Review runs under their target Claim, and new
operational records use workspace-wide `calc_n`, `sub_n`, and `op_n` ordinals.
Human-facing navigation uses these readable ordinal IDs. Opaque `ws_*`
workspace identities, `ctx_*` projection bindings, revisions, and digests remain
machine/audit fields; routine Pi and Web views show workspace labels and semantic
state instead of presenting those bindings as navigational IDs.
Review advice and Compute or deterministic tool results become scientific
support only after the Root Agent verifies primary artifacts and records normal
Observations through a Decision.

## Validation

Run validation from the authored checkout, not an installed release:

```bash
python3 scripts/test_source.py --conda-root /path/to/miniforge3 --with-render -- -q
npm run typecheck
npm run test:pi-adapter
python3 scripts/check_package.py
NPM_CONFIG_CACHE=/tmp/ts-agent-npm-cache npm pack --dry-run --json
git diff --check
```
