# Maintainer Guide

This guide covers development, validation, release, and documentation ownership
for `@iawnix/ts-agent`. Change the authored Git checkout only.
Installed releases are immutable runtime artifacts and must never be patched in
place.

Read [Architecture](ARCHITECTURE.md) before changing a cross-module contract,
[Installation and Operations](INSTALLATION.md) before changing lifecycle or
configuration, and [ADR 0001](adr/0001-phase-node-research-kernel.md)
before changing the research graph or validation architecture.

## Non-Negotiable Boundary

```text
Root Agent       research questions, strategy, method choice, interpretation
Research Kernel  canonical graph, identities, transactions, integrity
Validation       frozen policy, deterministic predicates, acceptance snapshots
Review Agent     bounded independent advice only
Compute Agent    fixed operational plan over pre-bound typed tools only
Tool plane       deterministic compute kernel, artifacts, remote, and delivery effects
UI/web           read-only projection
```

Only `ts_workspace_decision_apply` writes canonical scientific state. Compute
and Review are the only child models. Compute may orchestrate only its closed,
host-bound lifecycle; it cannot choose chemistry, arguments, paths, outcome, or
provenance. Render and Report remain direct deterministic tools.

Closed enums are justified only when code executes a closed contract. Research
questions, Claim types, relation meanings, Observation concepts, Finding types,
validation dimensions, Phase titles, Node tags, methods, and strategy rankings
remain open scientific vocabulary. The Kernel contains no Phase lifecycle,
prescriptive stage, Node type, scientific role/layer, or next-action router.

## Repository Map

| Path | Owner and purpose |
| --- | --- |
| `skills/transition-state-workflow/` | public Root Skill, focused references, and examples |
| `extensions/ts-workflow-control/` | context, Decision draft/validate/apply, package-source guard |
| `extensions/ts-workflow-review/` | advisory Review entrypoint and Root disposition |
| `extensions/ts-workflow-compute/` | Compute subagent entrypoint, bound action tools, and remote diagnostics |
| `extensions/ts-workflow-artifacts/` | deterministic structure seed/comparison, input import, Render, Report, and notification tools |
| `extensions/ts-workflow-ui/` | startup, editor/footer, TS Activity, Compute/Review history |
| `extensions/shared/` | public tool inventory and shared UI/path helpers |
| `src/agent-core/` | shared task/result validation, provider failure propagation, lifecycle, journals |
| `src/agents/compute/` | Compute task plan, isolated runtime, result derivation, and private prompt |
| `src/agents/review/` | Review task projection, prompt, result tool, semantic validation |
| `src/artifacts/` | deterministic render/report request and path validation |
| `pyproject.toml` | `ts-agent-kernel` metadata, dependencies, package discovery, and wheel data |
| `scripts/_wheel.py` | temporary-copy wheel build, metadata inspection, and release-wheel verification |
| `python/ts_agent/` | the single import namespace for all deterministic Python code |
| `python/ts_agent/workspace/` | graph state, bootstrap, Decisions, context, validation, transactions |
| `python/ts_agent/validation/` | GateSpec compiler, predicate registry, templates, acceptance profiles |
| `python/ts_agent/compute/` | capabilities, artifact catalog, immutable intents, control, collection |
| `python/ts_agent/backends/` | deterministic program preparation and parsing |
| `python/ts_agent/remote/` | OpenSSH/SCP, Torque, transfer, diagnostics, guards, and receipts |
| `python/ts_agent/runtime/` | runtime resolution, capability probe, and TSPi lifecycle host |
| `python/ts_agent/render/`, `python/ts_agent/report/`, `python/ts_agent/email/` | deterministic artifact and delivery services |
| `python/ts_agent/structures/` | molecular comparison plus deterministic RDKit seed generation |
| `python/ts_agent/web/` | read-only workspace projection and external UI registry |
| `docs/` | installation, architecture, maintenance, and ADRs |
| `tests/` | unit, contract, package, and recording-provider regressions |

`TSPi` remains a thin shell shim. Lifecycle logic belongs in
`scripts/tspi_host.py` and `python/ts_agent/runtime/launcher.py`; do not move release
selection, config, runtime resolution, bootstrap, locking, or Pi arguments into
shell.

## Public Package Surface

`package.json` registers exactly:

- one Skill: `skills/transition-state-workflow/`;
- five normal extensions: control, UI, Review, compute, and artifacts;
- one theme: `themes/ts-theme.json`.

`ts-phone-bridge` is packaged but loaded only by `TSPi --phone`. Files under
`src/agents/compute/` and `src/agents/review/` are private child-runtime
material, not discoverable Skills.

Public names describe authority:

- `ts_workspace_*`: deterministic context and canonical Decision pipeline;
- `ts_subagent_compute`, `ts_subagent_review`: bounded child-model entrypoints;
- `ts_structure_seed`, `ts_structure_compare`, `ts_artifact_import`, `ts_render`, `ts_report`: deterministic execution;
- `ts_remote_inspect`: deterministic read-only infrastructure diagnostics;
- `ts_review_disposition`: deterministic operational response;
- `ts_notify_user`: deterministic fixed-target external delivery.

Do not add alternate field readers, dual schemas, implicit state conversion, or
output shims. The package implements one explicit workspace contract.

The release ships runtime code, public docs, Root Skill, references, schemas,
templates, theme, and configuration examples. It excludes tests, build/check
scripts, Git metadata, dependency trees, caches, credentials, conversations,
workspaces, and generated reports.

## Scientific Model

The stable concepts and their owners are:

- **ResearchPhase**: human navigation metadata only. Every Node has one Phase;
  Phase never controls lifecycle, policy, or next action.
- **Claim**: Root-authored scientific statement, assumptions, falsifiers,
  status, and cited scientific records.
- **ClaimRelation**: open scientific relationship between Claims. The Kernel
  checks identity and acyclicity only.
- **ResearchNode**: one user-visible research decision episode with one Phase,
  short title, one question, one principal deliverable, dependency edges, Claim
  scope, linked records, and terminal result. The Kernel checks the DAG; it does
  not choose the successor.
- **Observation**: immutable typed semantic value with exact artifact digests
  and provenance.
- **Finding**: explicit anomaly, limitation, conflict, or open question.
- **GateSpec**: frozen expanded validation policy with registry and content
  digests.
- **ValidationResult**: deterministic predicate outcomes over selected,
  digest-bound Observations.
- **Acceptance record**: immutable snapshot verified against a versioned
  profile.

Tags and relation types must never select an allowed action, backend, validation
template, successor Node, or Claim status. New strategies normally require Root
reasoning and focused documentation, not a Kernel enum.

## Mutation Invariants

- New canonical state uses `ts-workspace/5` and
  `ts-research-kernel/5` only.
- Bootstrap initializes fresh state once and otherwise validates without
  canonical rewrites.
- The Decision draft accepts high-level research operations and local aliases; the
  Kernel allocates all `dec_`, `claim_`, `rel_`, `node_`, `obs_`, `fnd_`, `gsp_`,
  `val_`, and `acc_` identifiers.
- A draft binds the current frontier projection and workspace revision.
- Dry-run validation applies the full Decision to an isolated post-state.
- Apply repeats binding and post-state validation under the lock.
- All canonical research record IDs are readable workspace-local monotonic
  ordinals; draft allocation has no reservation, and revision binding prevents
  conflicting record allocation. Durable transaction history additionally
  prevents Decision ID reuse.
- Treat `ws_*`, `ctx_*`, revisions, and digests as opaque machine bindings.
  Preserve them in schemas, remote ownership, and audit artifacts, but keep
  routine UI labels and history rows on workspace labels and readable ordinal
  record IDs.
- A Decision ID is idempotent only for identical canonical content.
- Any edit to a returned Decision requires a fresh draft.
- One Decision may create at most one Phase, start at most one Node, and
  complete at most one Node. It may start and complete that same Node; closing
  an existing Node and opening another requires an explicit successor edge.
- The transaction owner writes the Decision snapshot, proposed documents,
  decision log, and committed transaction record in its declared order.
- Graph edges must be referentially valid and acyclic.
- Artifacts must remain in the workspace and match recorded digests.
- Pending Review disposition is an operational obligation that blocks the next
  scientific mutation but is not itself science.

No extension, parser, backend, remote worker, renderer, reporter, notifier, UI,
or web process may edit root state files directly.

## Validation Engine Rules

Keep reusable mechanism in the engine and scientific policy in data:

- templates are versioned parameterized prototypes;
- compilation fully expands a template and freezes its digest;
- predicates are registered deterministic code with one registry digest;
- a GateSpec may use a template or an explicit declarative check list;
- Agent-supplied executable code, shell, imports, and expressions are rejected;
- evaluation selects explicit Observation refs and binds their digests;
- predicate output refs must be a subset of that selected Observation snapshot;
- acceptance profiles declare required dimensions and coverage rules;
- acceptance requires a supported Claim and at least one passing GateSpec;
- open blocking Findings prevent acceptance;
- historical acceptance remains immutable, while currentness is one shared
  derived projection used by Context, Report, and Web.

Do not add a switch statement for each new scientific domain. Add a maintained
predicate only when existing predicates cannot express the observation-level
check. Add a template when a reusable scientific policy exists. Add or revise
an acceptance profile only when the acceptance standard changes.

Templates must be frozen before evaluating the selected data. Never lower a
GateSpec after seeing a result; create a new specification and preserve the
previous result.

## Agent Contracts

Compute and Review use `ts-agent-task/2` and return `ts-agent-result/1`. Shared
code owns role/authority identity, provider-failure priority, session lifetime,
journal bounds, and forbidden authoritative fields. Role-specific builders and
validators own their distinct input, capability, action, and result rules.

### Review

Every Review uses `ts-agent-task/2` and returns `ts-agent-result/1`. Its scope is
one target Claim and a bounded graph snapshot. It cannot set Claim status,
create Observations, evaluate a GateSpec, accept a Claim, perform compute, or
write canonical state.

The runtime must preserve these invariants:

- fresh child session with no parent transcript;
- `ts_review_result` plus an optional task-bound `ts_review_artifact_read`;
- no artifact content or physical path in the initial provider packet;
- at most one successful artifact-read batch, six section requests, 4 KiB per
  excerpt, and 12 KiB total;
- forced result-tool choice after artifact read and during repair, without
  provider-side strict function mode;
- no Skills, extensions, direct filesystem, shell, network, compute, or recursion;
- compact task projection and canonical citation allowlist;
- local TypeBox plus semantic validation;
- at most one same-session structural repair;
- provider HTTP/stream failure outranks missing-tool/schema failure;
- invalid raw output is private, bounded, operational, and never auto-ingested;
- artifact-read journals contain digests, line ranges and byte counts, never
  copied source text;
- exactly one Root disposition before the next scientific mutation.

Citation arrays are sets with canonical ordering. Never compare them using
registry insertion order. Dependencies derive from the Claim/Node graph and
explicit refs, not role or layer taxonomies.

### Compute

The Compute task binds one Node, backend, intent ID/digest, remote execution, and
one exact plan: `launch`, `inspect`, `finalize`, or `cancel`. The child must have
only the zero-argument action tools for that plan plus `ts_compute_result`.
Dependent actions require a completed prerequisite, every action is single-use,
and unknown submit/cancel effects end the plan without replay.

The result model may provide only `summary` and `limitations`. Code derives the
complete result from the action journal and rejects invented artifacts, changed
intent identity, mismatched program state, or fabricated outcome/provenance.
`inspect` deliberately permits either direct result delivery after `status` or
one `tail` before result delivery. Provider-side strict function mode remains
disabled; local TypeBox and semantic validators are authoritative.

## Deterministic Tool Contracts

### Compute

The Root selects purpose, Node, backend, task, settings, execution target, and
logical input artifacts when invoking `ts_subagent_compute`. The host owns
generated paths, filenames, intent ID, expected artifacts, remote root,
command, submission binding, action tools, and final structured outcome.

Preparation resolves `artifactId` and `inputRole`, verifies SHA-256, and writes
`ts-calculation-intent/5`. Subsequent operations cite only the bound `intentId`.
Backends prepare and parse program artifacts but never update Claims or produce
ValidationResults.

Keep these states separate:

- typed tool return versus action success;
- pre-effect validation/staging failure versus ambiguous external effect;
- known job ID versus unavailable scheduler history;
- scheduler completion versus program completion;
- program failure versus scientific contradiction;
- parser failure versus program failure.

Never infer success merely because a deterministic tool returned structured
JSON.

### Structure seed, comparison, and artifact import

The first input in a fresh workspace enters through `ts_structure_seed` or
`ts_artifact_import`. Structure seeding owns fixed ETKDG parameters, one
connected SMILES, chemical metadata checks, content-addressed XYZ/provenance,
and the explicit rule that a generated geometry is not evidence. Import remains
bounded inline UTF-8 in registered formats. Both require one open Node, mode-0600
files, no caller path, no symlink/overwrite path, and digest-only activity
requests. Their returned `art_*` is consumed by the ordinary Compute contract.

Structure comparison takes two registered XYZ IDs and delegates scientific
geometry logic to `ts_agent.structures`. `ts_agent.compute.artifacts` owns workspace
resolution, exact input-digest binding, the private no-overwrite
`outputs/analysis/` artifact, and request validation. The result is operational;
only a later Decision may register selected values as Observations.

### Render and Report

Artifact requests bind an existing Node and logical artifact IDs. Path policy is
Kernel/host-owned, rejects symlink traversal, and creates no-overwrite outputs.
Report creation validates the complete workspace and atomically installs a
manifest-bound package. Optional report images enter through logical artifact
IDs, are copied into `assets/`, and are indexed by digest. A report is derived
output, not a canonical writer.

### Remote and notification

`ts_remote` is the only remote subsystem. It binds installation-owned SSH,
Torque, storage, software, and resource policy. Preserve known job IDs, durable
guards, receipts, and ambiguity semantics. Collection must not require queue
history.

Notifications bind a configured fixed recipient and credentials outside the
workspace. The Root selects only event, subject, bounded summary, and allowed
manifest-listed report attachments. `notifications.toml` is the only recipient
authority. CLI failures must remain structured through the TypeScript adapter;
known delivery is idempotent and ambiguous delivery is not automatically
retried.

### Web projection

`ts_web` is read-only derived state. Keep Phase grouping, Claim/Node association,
acceptance currentness, operational identity, and file visibility in shared
projection helpers rather than duplicating policy in browser JavaScript. The
default UI must remain Node-first and show the Research Trajectory: opening
rationale, outcome, dependency lineage, branches, and merges. Phase is a
navigation filter, never a lifecycle lane. Atomic Decision operations and the
raw Claim graph belong under detail or advanced inspection; do not duplicate the
Node DAG in Advanced Graphs. Merge bounded trajectory fields into existing Node
payloads rather than returning a second full graph-shaped Node payload.

Calculation Attempts remain Node-owned operational records. Project their
purpose, kind, recalculation lineage, bounded settings, execution request, and
Compute runs from the immutable calculation intent and journals in
`ts_agent.web.normalize`; browser code may format or collapse that projection but
must not parse program outputs, infer scientific meaning, or turn Attempts into
ResearchNode DAG vertices.

The Web registry is external state and must never be created inside a source
workspace. Do not add write routes, implicit workspace repair, cached canonical
indexes, or arbitrary workspace file reads. New static assets must be added to
both `package.json.files` and the package/installer runtime checks.

Keep managed workspace discovery in `ts_agent.web.registry`, not the HTTP handler or
browser. Reconciliation may update only the external registry: discover direct
workspace children, prune missing entries only when the managed root was readable, and
preserve manual registrations outside managed roots. Tests must cover discovery,
stale rows, unavailable roots, and a catalog refresh after server startup.

Keep live refresh and release restart separate. Live refresh must use the
revision-aware snapshot projection, return no View/Graph when unchanged, and
retain the last valid browser state on transport failure. Release restart must
watch only the stable installed entrypoint, wait for the selected release's
managed runtime, close the server cleanly, and replace the process with `exec`.
Do not add in-process Python reload, workspace-local watcher files, or a hidden
development file watcher to this production lifecycle.

## Runtime Durability Semantics

Do not document stronger durability than the implementation provides:

- Compute/Review tasks and Review-bound inputs are atomically exclusive-created;
- agent actions/result/final run state are written during normal terminal
  handling;
- a crash can leave a pending/unknown agent journal;
- no background result replay or acknowledgement queue exists;
- immediate tool return is the active conversation delivery channel;
- deterministic tools keep separate authoritative records;
- `TS Activity` is transient and cleared with the Pi session;
- its normal row contract is kind, semantic owner, action, state, and elapsed
  time, without run IDs or audit paths;
- `/ts-subagent-history` reads durable Compute and Review summaries on demand,
  lists canonical `sub_n` IDs, and orders details as outcome/error, scope,
  actions/artifacts, then audit metadata.

Remote controls are authoritative for scheduler recovery. Activity or agent
journal state cannot prove that a remote side effect did or did not happen.

## Documentation Ownership

| Document | Audience | Owns |
| --- | --- | --- |
| `README.md` | first-time reader | product boundary, quick install/start, public surface, navigation |
| `docs/INSTALLATION.md` | installation operator | prerequisites, configuration, startup, upgrade, rollback, recovery |
| `docs/ARCHITECTURE.md` | maintainer/advanced operator | ownership, lifecycle, persistence, context, validation, delivery |
| `docs/MAINTAINER_GUIDE.md` | contributor/releaser | source workflow, change matrix, validation, release discipline |
| Root `SKILL.md` | Root Agent | concise authority rules and operating loop |
| Skill `references/*.md` | Root Agent on demand | one focused scientific or tool topic |
| `src/agents/compute/**/*.md` | Compute runtime | minimum private operational policy |
| `src/agents/review/**/*.md` | Review runtime | minimum private Review policy |
| JSON/TypeBox schemas | callers and validators | exact fields, enums, limits, identity |

Avoid copying complete field schemas into prose. Use examples where they
clarify an interaction and validate them against real code. Tests must not be
the only public examples.

Normal research sessions learn operation from registered tool schemas, live
context/capability catalogs, the Root Skill, and focused references. Source and
tests are maintenance material and are blocked by the package-source guard.

## Contract Change Matrix

| Change | Required surfaces |
| --- | --- |
| Canonical record or Decision operation | JSON schema, draft normalizer, engine/validator, templates, Skill/reference, report/web projection, tests |
| Graph topology | schema, validator, context traversal, Review snapshot, report/web, cycle/backtrack tests, architecture |
| Observation concept | producer/parser, validation template/predicate, scientific reference, fixtures, tests |
| Predicate | registry, implementation, digest behavior, unit tests, capability projection, maintainer docs |
| Validation template/profile | versioned JSON, compiler/acceptance tests, capability projection, scientific docs |
| Public tool | tool catalog, extension schema/help, Root Skill, README/architecture, UI, inventory tests |
| Compute/Review task or result | JSON schema, CJS validator, role packet builder, result tool, journal/history, provider tests |
| Backend capability | capability catalog, request validator, adapter, compute reference, parser tests |
| Remote behavior | config/model, lifecycle/transfer, compute mapping, installation/remote docs, recovery tests |
| Release contents | `package.json.files`, package checker, installer allow/deny lists, tests, installation docs |
| Startup behavior | Python host, launcher tests, installation docs, architecture lifecycle, launch smoke |

Documentation tests should assert entrypoints and architectural invariants, not
freeze cosmetic wording.

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

Use the package runtime wrapper if the host interpreter lacks declared
dependencies:

```bash
python3 scripts/ts_runtime.py run -m pytest -q
python3 scripts/build_release.py --allow-dirty --output-dir /tmp/ts-agent-release --json
```

This is an Agent-component development probe. The builder creates the wheel
from a temporary source copy, then adds
it to the final npm archive under `python-dist/`. Do not use the immutable
release directory itself as a PEP 517 build source; setuptools needs writable
build-metadata space. The runtime installer consumes the bundled wheel and
never writes build metadata into authored or installed package roots.

Do not install project dependencies into a shared Conda base. Keep credentials,
conversations, caches, workspaces, release archives, and generated reports out
of tracked source.

## Validation Tiers

Run the narrowest relevant check first, then all shared checks for public or
cross-module changes.

### Documentation or Skill

```bash
python3 -m pytest -q tests/test_readme_contract.py tests/test_report_template_contract.py tests/test_decision_templates.py
python3 scripts/check_package.py
git diff --check
```

### Python kernel or deterministic service

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
```

### Pi extension or Review runtime

```bash
npm run typecheck
npm run test:pi-adapter
```

The recording-provider suite covers public inventory, Review isolation,
provider failure propagation, result repair, journals, and UI lifecycle without
contacting a production model endpoint.

### Package and release

```bash
# TS Phone repository
npm run test:release
npm run typecheck
npm test
npm run build
python3 deploy/build-component-release.py --output-dir dist/component --json

# TSPi repository
python3 scripts/check_package.py
NPM_CONFIG_CACHE=/tmp/ts-agent-npm-cache npm pack --dry-run --json
python3 -m pytest -q tests/test_suite_release.py tests/test_release_install.py
python3 scripts/build_package.py \
  --phone-manifest /path/to/ts-phone/dist/component/ts-phone-component-release.json \
  --output-dir dist/package \
  --json
```

Inspect `tspi-package-release.json`. Confirm that its Agent descriptor matches
the sole nested wheel, its Phone descriptor matches the server and signed APK,
its protocol set is exact, and its nested archive paths and digests match the
outer archive. One suite release ID must select the entire component set.

Both component builds require clean checkouts. `--allow-dirty` is only for
local smoke validation and must not be distributed.

## Version Changes

Package version metadata currently appears in multiple maintained surfaces. A
version bump must update and test at least:

- `package.json` and `package-lock.json`;
- `pyproject.toml` and `python/ts_agent/_version.py`;
- `extensions/shared/package-profile.ts`;
- `scripts/check_package.py`;
- contract-specific tests and release fixtures.

Schema versions change only when data contracts change, not whenever the
package version changes. Validation template/profile versions are independent
policy versions and must be bumped when their expanded meaning changes.

## Release Procedure

1. Inspect `git status` in both source repositories and preserve unrelated
   changes.
2. Run focused tests, full Agent pytest, both TypeScript checks, Pi adapter
   tests, Phone tests/build, and Package checks.
3. Confirm docs, examples, CLI help, schemas, and registered tools describe one
   workspace contract.
4. Commit only intended source changes in their owning repositories.
5. Build the Phone component and complete Package from clean commits. Record
   both source commits, component IDs, suite release ID, archive size, and
   SHA-256.
6. Install into staging or the authorized TSPi root with
   `install_package.py`.
7. Resolve the selected Agent component's isolated Python runtime.
8. Verify `TSPi --help`, `TSWeb --help`, `TSPhoneCtl --help`,
   `TSPhoneServer --help`, all launchers' release identity, fresh workspace
   bootstrap, tool inventory, and optional read-only remote status.
9. Restart user sessions only in an authorized maintenance window.

The installer atomically selects `current`; running processes retain the release
and runtime with which they started. Installation does not modify workspaces or
remote jobs.

## Rollback Discipline

Preserve every distributed Package archive and manifest. Roll back by selecting
the previous pair through the suite installer, resolving its Agent runtime, and
starting new TSPi, Web, and Phone processes as needed. Do not mix independently
selected component versions, edit installed files, or run Git operations inside
a release directory.

Rollback never converts canonical state. The selected release must implement
the workspace schemas it opens.

## Review Before Handoff

- Does each changed rule have one owner?
- Do schemas, draft normalization, engine behavior, docs, templates, CLI help,
  UI, and tests agree?
- Did any alternate state reader, alias, Node/Evidence record, Phase lifecycle,
  role/layer router, fixed Gate branch, or deterministic child model return?
- Can a new installer start and resume a fresh workspace from the docs?
- Can the Root Agent tell reasoning, canonical mutation, deterministic effects,
  and presentation apart?
- Are crash, ambiguity, and delivery limits explicit?
- Are new scientific dimensions extensible through templates/predicates rather
  than workflow branching?
- Were unrelated user changes preserved?
- Is every claimed validation backed by a completed command?
