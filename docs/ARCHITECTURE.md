# TSPi Package Architecture

This document defines component ownership and runtime boundaries for
the TSPi Package and its `@iawnix/ts-agent` component. JSON and TypeBox schemas are authoritative for
field-level call shapes. `tspi-orchestration` is authoritative for task and
contract behavior; focused Skills provide scientific-method and output/delivery guidance. [ADR 0001](adr/0001-phase-node-research-kernel.md) records the
Phase + ResearchNode design.

## System Shape

```text
Installation root
  one selected TSPi Package release
    Agent + selected optional Web and Phone components
  TSPi shell shim
    -> Python lifecycle host
       -> immutable selected release and isolated Python runtime
       -> workspace bootstrap and one-writer Root lock
       -> Pi process
          -> orchestration Skill + focused Skills + five extensions + theme
          -> Root Agent
             -> Research Kernel
                ResearchPhase roadmap + ResearchNode DAG + Claim graph
                Observation and Finding registries
                Decision transaction owner
          -> deterministic execution plane
                compute kernel + Render + Report + remote + notification
             -> Validation Engine
                frozen ProofSpecs + registered predicates + acceptance profiles
             -> graph Context Compiler
             -> isolated operational Compute Agent
             -> isolated advisory Review Agent
          -> read-only TS Activity and history projection
```

There are three forms of execution:

1. **Root Agent reasoning** selects scientific questions, hypotheses, methods,
   alternatives, counterexamples, backtracking, stopping, and interpretation.
2. **Bounded child-agent execution** has two roles. Review evaluates a compact
   Claim-centered snapshot and returns non-authoritative advice. Compute
   orchestrates one host-bound action plan and has no scientific discretion.
3. **Deterministic host execution** validates and commits state or performs an
   explicitly selected side effect. Every compute action, structure seed or
   comparison, Render, Report, remote inspection, artifact import,
   notification, context, and validation operation is implemented outside the
   child model.

## Package Release Boundary

Source ownership and release ownership are deliberately different. TSPi and TS
Phone remain separate Git repositories with independent tests and maintainers.
The Web source is an independent component boundary under
`components/ts-web/`; its provider client and browser UI do not import the
Agent kernel. TSPi owns the projection provider and the suite assembly. TS
Phone produces a deterministic component archive; it does not select the
installed TSPi version.

The TSPi suite assembler consumes zero or one validated Phone component
manifest, builds or consumes one Agent component, checks the selected protocol
and artifact contracts, and writes `tspi-package-release/4`. Web is selected by
the assembler unless `--without-web` is supplied. The Phone boundary
requires `ts-phone-component-release/2`: its signed APK embeds a source
snapshot, and a manifest-bound attestation binds that snapshot to the APK
digest, version, build, ABI, and pinned signer. TSPi independently verifies
those facts during assembly and installation. The outer Package contains the
required Agent archive and the selected optional component archives, and records
their schema and protocol identities. In `/4`, the selected Web archive is
extracted under `current/web/`, separate from Agent. `install_package.py` first captures the
caller-supplied Package archive
into private staging so hashing, inspection, and extraction consume the same
bytes. It then verifies every layer, prepares and probes the
release-bound Python runtime, and only then selects exactly one set at:

```text
<installation>/.pi/packages/tspi/current
```

Top-level `TSPi`, `TSWeb`, `TSPhoneCtl`, and `TSPhoneServer` symlinks all pass
through that pointer. The three conversation entrypoints share `agent/TSPi`;
their invoked name selects terminal, Host, or control CLI. Python validates the
selected suite before `apps/host/entrypoint.mjs` imports its Phone component.
`apps/host/environment.mjs` is the shared private dotenv reader for all three:
explicit environment overrides installation configuration, then defaults.
No shell evaluation, scientific bootstrap, global Pi changes, or credential
copies occur while starting a UI or the Host. Runtime configuration, model credentials, SSH settings,
notification settings, Phone tokens, Pi sessions, workspaces, and service state
remain outside releases. Package installation never starts a service or installs
the Android APK.

## Python Distribution Boundary

The Pi package and Python distribution are separate, coordinated boundaries.
`package.json` selects the Pi resources and immutable release contents.
`pyproject.toml` builds the deterministic kernel as `ts-agent-kernel` from the
single `packages/ts-agent-kernel/ts_agent/` namespace. Stable `scripts/*.py` files remain Pi and
operator entrypoints; they do not own domain behavior.

`build_release.py` is the internal Agent component builder. It builds the wheel
from a temporary writable source copy and embeds it under `python-dist/`.
Component manifest `ts-agent-release/2` binds the wheel name, version, path,
size, SHA-256, and expanded package-payload digest to the Agent archive.
`build_package.py` binds that component into the selected Package;
`install_package.py` is the public installation boundary. `install_release.py`
remains available for Agent-component development tests, not full deployments.

The runtime store has two content-addressed layers. `base/<spec-hash>` is a
shared Conda environment that owns scientific and rendering dependencies.
`kernels/<payload-hash>` is a small `--system-site-packages` venv that owns the
exact `ts-agent-kernel` wheel for one Python payload. A dependency-only change
creates a new base; a kernel-only change creates a new overlay without solving
or reinstalling RDKit.

`install_env.py` is only the command-line boundary; `_runtime_install.py` owns
the reusable preparation and publication mechanism. It never builds inside an
immutable release. It revalidates the bundled wheel and installs it into the
overlay without dependency resolution. From an authored checkout, it builds
the same wheel in a temporary directory and installs that artifact without
creating `egg-info` in the checkout. The runtime probe hashes every installed
Python module and package-data file, asserts NumPy/RDKit origins are inside the
base, and asserts the distribution is inside the overlay. The external
`ts-agent-runtime/2` manifest binds those origins and capabilities to both
content digests. Version 1 manifests are stale by definition and are not
silently converted.

Package activation is prepare, probe, then publish. A failed preparation leaves
the old `current` and runtime manifest untouched. A failure while publishing the
manifest, pointer, install state, or stable links restores their previous
values. Prepared immutable releases and overlays remain available for diagnosis
and retry; service restart remains a separate operator action.

## Authority Matrix

| Component | Uses a model | Writes canonical science | External effect | Durable output |
| --- | --- | --- | --- | --- |
| TSPi lifecycle host | No | Bootstrap only | Starts Pi | release/config selection, identity, Root lock |
| Root Agent | Yes | Only through `ts_change` | Selects bounded tools | Pi conversation and applied Decisions |
| Research Kernel | No | Yes, exclusively | No | graph registries, acceptance, Decisions, transactions |
| Context Compiler | No | No | No | revision-bound read projection |
| Validation Engine | No | Through Kernel apply | No | frozen ProofSpecs and ValidationResults |
| Review Agent | Yes | No | No | task, snapshot, result/failure, Root disposition |
| Compute Agent | Yes | No | Only through bound typed tools | task, actions, deterministic result/failure |
| Compute kernel | No | No | Local preparation/parsing or SSH/Torque action | intent, control record, manifest, parsed artifacts |
| `ts_seed` | No | No | Bounded local generation | Node-owned XYZ, provenance, and activity |
| `ts_compare` | No | No | Bounded local analysis | Node-owned JSON, input digests, metrics, and activity |
| `ts_import` | No | No | Bounded local file creation | Node-owned content-addressed input and activity |
| `ts_render` / `ts_report` | No | No | Local file creation | no-overwrite artifact or report package |
| `ts_remote` | No | No | Read-only SSH/Torque calls | tool result only |
| `ts_notify` | No | No | Fixed-target ClawEmail delivery | digest-addressed receipt |
| TSPi UI and `ts_web` | No | No | Read-only projection | transient UI or explicit UI registry |

Only `ts_change` may mutate canonical scientific state after
bootstrap. No extension, Review result, backend, parser, scheduler, renderer,
report builder, notification, UI event, or Agent prose may bypass that owner.

## Scientific State Model

### Claim graph

A Claim contains a scientific statement, open `claim_type`, assumptions,
falsifiers, tags, status, and exact Observation/validation history. A separate
ClaimRelation record connects two Claims with an open scientific relation label
such as dependency, refinement, conflict, or alternative. The Kernel enforces
acyclic directed relations but does not interpret a label as permission to
start a Node.
ClaimRelation IDs are readable workspace-local ordinals (`rel_1`, `rel_2`, ...).
Claim IDs are workspace-local monotonic ordinals (`claim_1`, `claim_2`, ...),
used only as immutable identity and never as confidence, priority, or policy.
`ResearchNode.claim_refs` records Claims in a Node's declared scope, while
`Claim.created_by_node` records the Node in which a new Claim originated. They are
not mirrored fields. Read projections derive the Claim-Node neighborhood from
their union so provenance-only links remain visible without canonical rewrites.

### ResearchPhase roadmap

A ResearchPhase is a narrow human-navigation record: readable ordinal ID,
title, objective, creation Decision, and timestamp. Every ResearchNode belongs
to exactly one Phase. A Phase has no status, successor rule, method policy,
validation policy, or permission meaning. Cross-Phase Node dependencies remain
valid. Reports and `ts_web` may derive Node counts for display, but never write
derived Phase state.

### ResearchNode DAG

A ResearchNode is one bounded, auditable, and user-visible research decision
episode. It records:

- one Phase, a short human-facing title, one objective, and one principal
  deliverable;
- zero or more dependency Nodes;
- one optional primary Claim, additional related Claims, and descriptive tags;
- Observations, Findings, ProofSpecs, and ValidationResults linked by canonical
  scientific refs;
- one terminal result or an open status;
- the Kernel-owned artifact root `nodes/<node_id>`.

Dependencies form a DAG. One dependency creates an ordinary continuation;
multiple dependencies model a merge; a new Node that depends on an earlier Node
models backtracking. Prior Nodes are never rewritten or deleted to make a later
path look linear. The DAG records lineage and does not select the next Node.

Node granularity follows scientific purpose, not a fixed number of operations.
One Node owns one principal question and deliverable. Exact retries and method
or setting variations used to answer that same question remain Attempts, while a
changed objective, independent scientific branch, or principal deliverable
starts a dependent Node. Scientific hypotheses, assumptions, and falsifiers
remain on Claims so multiple Nodes can test the same statement without copied
state. This is authoring guidance, not Phase lifecycle or Kernel permission.

One canonical Decision may start at most one Node and complete at most one
Node. It may start and complete that same Node; closing an existing Node and
opening another atomically requires an explicit successor edge. The shared
read-only Research Trajectory derivation joins each Node to its opening and
completion Decision summaries. Report uses the complete projection, while
Context and Web consume bounded fields derived from it; it is not another state
store.

### Observation and Finding

An Observation is immutable and semantic. It binds a `concept_id`, subject,
typed value, unit, qualifiers, summary, logical artifact IDs, artifact digests,
producer, producing Node, and creating Decision. Parsers must emit declared
concepts directly; the Kernel does not guess aliases for arbitrary output keys.
Observation IDs are readable workspace-local ordinals (`obs_1`, `obs_2`, ...);
the record fields, not the ordinal, carry scientific meaning.

A Finding makes an anomaly, conflict, limitation, or unresolved question
queryable. It may cite Claims, Nodes, and Observations. Findings can be blocking,
warning, or informational. A Finding remains open until an explicit Decision
resolves, accepts, or supersedes it. Open blocking Findings prevent acceptance
of affected Claims.
Finding IDs are readable workspace-local ordinals (`fnd_1`, `fnd_2`, ...).

### Validation and acceptance

A ProofSpec is a fully expanded, frozen declarative check set. It records the
target Claim, dimension, template digest when applicable, predicate-registry
digest, checks, success policy, creator Node, and content digest. A
ValidationResult records selected Observation refs and digests, each predicate
outcome, the aggregate verdict, and a result digest.
ProofSpec and ValidationResult IDs are likewise readable creation ordinals
(`proof_1`, `proof_2`, ... and `result_1`, `result_2`, ...).

The four verdicts are distinct:

```text
pass | fail | inconclusive | error
```

`inconclusive` means available valid inputs cannot decide the specification.
`error` means the specification could not be executed as declared. Neither is
a passing result.

Claim status is an explicit Root interpretation; acceptance is a separate
immutable assessment snapshot. A versioned acceptance profile checks a
supported Claim, at least one ProofSpec, required dimensions, coverage of all
attached ProofSpecs, the latest passing result per specification, content
digests, and blocking Findings. Historical records remain canonical. Their
currentness is derived by comparing the frozen Claim, profile, ProofSpecs,
latest results, and relevant Findings with current canonical state. The entire
acceptance record is also self-bound by `acceptance_digest`.
Acceptance IDs and filenames use readable ordinals (`acc_1`, `acc_2`, ...).

### Open scientific vocabulary

Claim types, relation types, Node tags, Finding types, validation dimensions,
Observation concepts, and subjects remain open strings because they express
research meaning. Closed enums exist only where deterministic code must execute
a closed contract, such as record status, value datatype, finding severity,
validation verdict, and Decision operation.

There is no prescriptive stage, Phase lifecycle, Node type, scientific
role/layer, backend priority, or fixed Gate-to-action router.

## Canonical And Operational State

Canonical state is:

```text
workspace.json
research_state.json
phases.json
claims.json
claim_relations.json
research_nodes.json
observations.json
proof_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

These records determine `workspace_revision`. Direct edits are unsupported.

Operational or derived state includes:

```text
.ts-operational-ids.json
nodes/<node_id>/attempts/<calc_id>/...
nodes/<node_id>/attempts/<calc_id>/runs/<sub_id>/...
reviews/<claim_id>/runs/<sub_id>/...
nodes/<node_id>/outputs/...
nodes/<node_id>/activities/...
operations/activities/...
reports/...
.pi/ session and lock state
remote guards, receipts, and mirrored files
notification receipts
```

Operational state may determine `operational_revision`, but it does not change
a Claim, Observation, Finding, ValidationResult, or acceptance record.
Operational IDs are workspace-wide monotonic ordinals: `calc_n` for calculation
Attempts, `sub_n` for Compute/Review sessions, and `op_n` for deterministic
activities. Allocation is lock-protected, high-water based, private, and never
reuses a reserved ordinal. Operational projections index only canonical
ordinal-named journals and ignore unrecognized entries.

The presentation contract distinguishes navigational IDs from technical
bindings. Canonical and operational records expose readable ordinals such as
`claim_1`, `node_1`, `calc_1`, `sub_1`, and `op_1`. Immutable `ws_*` workspace
identities, content-bound `ctx_*` projections, revisions, and digests remain
opaque protocol and audit values. Normal Pi/Web chrome must show a workspace
label and semantic state, not use those opaque bindings as user-facing names.

`workspace.operational.calculation_attempt_index()` is the single interpreter
for the durable Attempt lifecycle. It validates the immutable
`intent.json`/`prepared.json` binding and any status/result documents, then
publishes two read-only streams: bounded `calculation_attempts` rows and
`calculation_attempt_integrity_findings`. A finding with
`scope=attempt_parent` describes an unsafe or unreadable `attempts/` parent; it
is never a synthetic `calc_*` Attempt and is excluded from the Attempt count.
All Attempt, Compute-run, Research Files, Context, API, and Web projections use
this index. Symbolic-link components are fail-closed: they are reported, never
enumerated or read outside the workspace. These operational diagnostics are
not scientific evidence and are excluded from the scientific `projection_id`.

## Decision Transaction

The only normal mutation boundary is:

```text
ts_state -> Root decision -> ts_change (compile, validate, apply under one lock)
```

`ts_change` accepts Root-authored research operations and local aliases. The
Kernel privately allocates technical IDs, resolves `$alias` references, compiles
any ProofSpec, evaluates requested validation against the proposed state, binds
the current scientific revision, and commits one complete `ts-research-decision/3`
without exposing an intermediate Decision to the caller.

The always-present tool schema carries only the stable operation envelope. For
an unfamiliar operation, Root requests
`ts_state mode=change_contract operation=<op>`; the Kernel builds that field
catalog from the same registry used by the compiler. This avoids both a copied
TypeScript union and repeated field guessing.

When a newly opened ResearchNode is the active work item, Root normally includes
the `set_focus` operation in that same Decision. Focus is navigation metadata,
not a scientific verdict; intentionally preserving another focus is allowed but
should be explicit in the Decision rationale.

The Kernel applies the proposed change to an isolated copy and validates the
complete post-state before committing while holding the workspace lock. A
replayed change is idempotent only when its full request digest matches the
recorded transaction. Decision IDs are workspace-local monotonic ordinals used
only as immutable audit identity; callers never reserve or patch them.

Supported draft operations are:

```text
create_phase            create_claim            relate_claims
start_node               complete_node
record_observation      record_finding      resolve_finding
freeze_proof_spec evaluate_proof
update_claim            accept_claim
set_focus
```

These are state primitives, not a prescribed sequence. A single Decision may
contain multiple ordered operations and refer to new records with local aliases.

## Validation Engine

The engine separates mechanism from policy:

```text
Proof template + typed parameters
  -> compiler expands every check
  -> frozen ProofSpec with template and registry digests
  -> registry invokes maintained deterministic predicates
  -> ValidationResult with selected Observation digests

Acceptance profile
  -> required dimensions + coverage rules + blocker rules
  -> immutable assessment snapshot + derived currentness
```

The Root Agent may select a packaged template or provide a declarative
definition composed only of registered predicates. A definition cannot contain
Python, shell, imports, expressions, or executable plugins. New deterministic
scientific behavior enters through maintained predicate code, tests, and a new
registry digest.

Built-in classical TS templates are ordinary packaged templates. Photochemical,
metal-catalyzed, radical, crossing, or dynamics work can add new templates and
predicates without adding a new workflow branch.

## Context Compiler

The model receives revision-bound graph projections rather than raw canonical
files. Graph modes are:

- `frontier`: focus Claims/Nodes, direct alternatives/dependencies, open
  Findings, incomplete validation, and recent object-level changes;
- `claim`, `node`, `finding`, and `proof`: one focused object and bounded
  neighborhood;
- `subgraph`: caller-seeded Claim/Node graph to a bounded depth;
- `delta`: changes since known scientific and operational revisions.

The same read-only public tool exposes `locate`, `artifacts`, and
`capabilities`. `locate` accepts one
exact ID or text query and joins Claims, Nodes, Observations, Attempts, and the
authoritative artifact catalog to bounded current paths. An Attempt result
distinguishes the frozen input bindings from the output artifacts it produced.
A Claim result includes only artifacts reached through its direct
`observation_refs`; related Node roots remain navigation, not implied evidence.
The projection is rebuilt on demand, creates no index file, and changes neither
scientific nor operational revision.

Every bounded graph projection reports omitted counts and retrieval hints. The
Pi transcript is conversational state, not a scientific source of truth.

Root context carries the compact Node trajectory in `workspace_brief`; it does
not repeat the full Research Trajectory projection already derivable from the
same bounded Nodes and immutable Decision snapshots. Reports and `ts_web` use
the same derivation for human presentation; Web merges the needed fields into
its existing Node records instead of returning another duplicate graph.

Claim-Node traversal uses the union of declared Node scope and Claim creator
provenance. Context, Review, report rendering, and `ts_web` share this derived
relationship; none mutates the underlying Claim or ResearchNode records.

Capability discovery is progressive: the catalog is compact, while an exact
proof `templateId` plus `templateVersion` returns that template's accepted
parameters and expanded Observation selectors before a ProofSpec is drafted.

## Read-Only Web Projection

`ts_web` is an external explorer, not another workflow runtime. Its registry is
stored outside every research workspace and maps a display label to one source
root. Each request validates the current workspace and rebuilds its view from
canonical records plus the operational projection; no Web index is canonical or
written back to the study.

An installation-layout registry has one managed discovery root at
`<installation>/workspaces`. Catalog startup and refresh reconcile only direct
children: new workspace identities are registered, missing managed sources are
removed, and external manual registrations are preserved. Discovery-root
failure is fail-safe and performs no pruning. This mutates only the operational
Web registry; it never initializes, repairs, or writes a research workspace.

The browser's live path uses one revision-aware snapshot request. The server
normalizes the workspace once, returns only scientific and operational revision
identities when unchanged, and returns the View and Graph derived from that same
normalization pass when changed. Browser polling is presentation state: it pauses
while hidden, preserves the current interaction, and never writes watcher state
into a research workspace.

The default navigation is a derived Research Map. Within each ResearchPhase it
separates dependency-free work shared by several Claims from Claim-owned
hypothesis lanes. Lane assignment uses the Node's primary Claim, then a sole
derived Claim association, and otherwise an explicit unassigned lane. This
grouping is presentation only: ResearchPhase still carries no lifecycle or
policy meaning, and a lane never mutates Claim or Node ownership.

Structured endpoint-assignment Observations are deduplicated into connectivity
evidence under the lane owning their creating Node. Their presence does not
project a validation verdict. They are displayed as undirected unless an
explicit `connectivity_direction` qualifier exists; labels such as reactant,
product, forward, or reverse are never interpreted as chemical direction. The
secondary Dependency DAG mode retains the exact cross-Phase
Node dependencies, branches, merges, and backtracking lineage with pan, zoom,
fit, and a narrow-screen outline.

Both modes identify the latest calculation state without promoting Attempts
into graph vertices. A Node's Overview shows only the compact Attempt and family
summary. Its Runs tab projects
immutable calculation intents as family-grouped, filtered, fixed-page records
with scientific purpose, primary/retry/recalculation kind, source Attempt,
derived changes, method, parameters, remote resource request, job/timing state,
expected artifacts, and bound Compute runs. The workspace snapshot carries only
compact Attempt fields; parameters, bindings, and execution resources are loaded
with the selected Node detail.
Node details otherwise separate conclusions, Evidence, operational activity,
files, and Decision history. Claims, acceptance, validation, Findings, the
Research Files locator, and operational activity remain separate views.
Scientific Conclusions offers Table and Map modes over one Claim projection.
The Map is an interactive, read-only presentation of ClaimRelation records and
does not duplicate the ResearchNode DAG or interpret relation labels as policy.

Operational overlays preserve their actual owners: calculation Attempts belong
to Nodes, Compute runs belong to Attempts, Review runs belong to Claims, and
deterministic activities cite their Node scope. A projected unresolved control
uses intent, operation, and control-attempt identity so submit and cancel effects
for one calculation cannot collapse into one row. A known pre-effect failure
with `retry_same_submission` is projected separately as retryable: it requires a
configuration fix, not reconciliation, and it does not block Node completion.

The HTTP API has no mutation route. File preview is limited to current
Node-owned files already admitted by the Node file projection, rejects symlinks
and traversal, and exposes a preview control only for UTF-8 text within the
byte limit. The server rechecks the same capability when the file is opened.
The server has no authentication
layer; operators must bind it to loopback or expose it only on a trusted,
firewalled network.

Long-running installed Web processes are invoked through the stable
`<installation>/TSWeb` path. A small lifecycle watcher compares
that path's resolved target with the entrypoint that loaded the process. Once a
new selected release and its managed Python runtime are both ready, it shuts
down the HTTP socket and `exec`s the stable command. The stable installation
layout supplies the installation-owned runtime manifest and environment roots
without overriding explicit operator configuration. Python modules are never
reloaded in process, so one process image cannot mix release implementations.
Authored-checkout source reload and zero-downtime socket handoff are outside this
mechanism.

## TSPi Lifecycle

`TSPi` is a thin shell shim. `scripts/tspi_host.py` and
`packages/ts-agent-kernel/ts_agent/runtime/launcher.py` own lifecycle behavior:

The default user route resolves the selected package and executes
`apps/terminal/index.mjs`. This route does not select scientific Python, load
Skills or model credentials, bootstrap a workspace, or acquire writer locks.
The terminal uses the existing authenticated Host API and Pi TUI components.
`--phone` aliases this route. `--standalone` explicitly selects native Pi.

The Host is the session broker for Phone and terminal clients. A conversation
is addressed by `workspaceId + sessionId`; attached clients share its Worker,
event journal, model state and command receipts. Browsing never activates Pi.
Normal sends are persisted before acknowledgement and enter one FIFO execution
lane per workspace. Concurrent starts share one in-flight launch, and repeated
client message IDs return their stored receipt. An interrupted execution stays
unknown until inspected; it is never replayed to repair a missing HTTP response.
SSE provides the latest snapshot plus newer events when a reconnect cursor is
too old. TS Web remains a read-only projection of the scientific workspace,
not another Agent or conversation writer.

The following lifecycle applies only to native Pi and Host-managed Workers:

1. Resolve the physical installation root and immutable selected release.
2. Resolve installation-owned runtime, remote, notification, and cache paths.
3. Select the isolated Python interpreter and verify its installed
   `ts-agent-kernel` payload before importing workflow code.
4. Validate the workspace name, hold the session-directory guard, and create or reuse
   `<installation>/workspaces/<name>`.
5. Create workspace-local Pi session settings and acquire a nonblocking Root
   Agent lock.
6. Initialize fresh state once or validate a complete workspace without
   rewriting it. Partial, invalid, or unsupported canonical state fails closed.
7. Resolve an exact Pi session ID, acquire its writer guard, and execute Pi
   with the package Skill family, theme, and five extensions. Skill bodies are
   loaded on demand; the orchestration Skill remains the cross-cutting contract.

The TS Phone Host uses private launcher operations. A
`--phone-worker` controller follows the same bootstrap and one-writer lock path,
then opens the requested Pi session ID in RPC mode; an observer resolves an
existing workspace without acquiring the scientific Root lock. Both modes
hold a shared directory guard and an exclusive session writer guard before Pi
opens JSONL. These owner-only OS guard files live under installation
`.pi/session-host/guards/`, keyed by workspace path and session ID. They remain
outside directories that lifecycle operations may quarantine. Descriptors
survive exec and stay held for the Pi process lifetime.

Managed Workers enter official Pi SDK/RPC through
`extensions/ts-phone-bridge/runtime.mjs`; normal TUI launch still uses Pi CLI.
The SDK Worker loads the same explicit package extension/Skill/theme inventory,
preserves the exact session ID and history, and merges global/project settings
into an in-memory preference store. A model switch changes this conversation's
Pi history, never shared defaults. `PI_CODING_AGENT_DIR` (default `~/.pi/agent`)
still owns credentials and the model registry. Saved history takes precedence
over a startup model preference; missing models fail without arbitrary fallback.
The private `--phone-models` entrypoint returns only available model identities,
names and context limits without bootstrap. The Bridge advertises model control
only for these session-local Workers. Queue-capable clients select the model for
future sends; each admitted request freezes that selection. The Host applies
it to an idle Worker and requires an exact RPC receipt before dispatch. Direct
selection also requires an idle Worker. External TUI settings are
not changed.

`--lifecycle-preflight` resolves an existing workspace and returns its absolute
path, actual Root/session-writer occupancy, and bounded counts of non-terminal remote
calculations and unresolved remote effects (`ts-phone-project-preflight/2`). It
does not load remote configuration, contact a scheduler, mutate canonical
state, or create missing workspace files. Operational-integrity uncertainty
fails the preflight closed.

Host-only `--lifecycle-guard` acquires the directory guard exclusively, then the
Root lock before inspecting
the workspace, returns `ts-phone-project-guard/1`, and retains ownership until
its stdin closes. It may create `.pi/root-agent.lock` but never bootstraps
scientific state or starts Pi. Phone holds this process through project trash
and permanent project/session deletion; failed acquisition blocks the action.
An old PID in an unlocked file does not count as an active Root Agent.

`--session-host-capabilities` advertises `tspi-session-guard/1` to the Host only
after the installer has recorded the same contract in owner-only
`.pi/packages/tspi/install-state.json`. A missing record blocks Worker/native
startup and destructive lifecycle operations, but not browsing or model catalog reads.
`--session-writer-check` verifies a Bridge PID against the held directory,
session, and (for Controller) Root flock descriptors in Linux `/proc`. A
configured Host refuses writers without that proof and binds managed Bridge
registrations to the exact spawned child PID and launch ID.
Normal startup and lifecycle preflight acquire actual workspace/session guards;
they never scan other Pi processes, their cwd, or their environment. A corrupt
guard is an error, not evidence of an active writer. PID files are descriptive;
only held OS locks grant ownership.

Process inspection runs once in the Package installer, before publishing
the installation guard record. It holds each affected workspace's directory and
Root locks across inspection and release activation. Run this upgrade as the
installation owner after old TSPi writers have exited; an unverifiable unguarded
candidate blocks the upgrade, not every future session startup. Subsequent
installs with the same guard contract skip process inspection. No process is killed.
Raw Pi and archived launchers bypassing the selected installation are outside
this cooperative guard boundary.

Before Pi starts, a failed `--phone-worker` guard check also emits one private
stderr JSON line: `{"type":"tspi.startup_error","code":"..."}`. The fixed codes
are `session_writer_active`, `session_writer_inspection_failed`, `session_guard_upgrade_required`, and
`session_guard_invalid`. The Host maps only these codes to safe errors; human
launcher diagnostics, environment values, and provider stderr stay private.
Capability, writer-proof, and lifecycle failures use the same fixed-code record; their errors
are not collapsed into `session_writers_active=true` or forwarded as raw stderr.

One workspace has one Root writer process. Different workspaces can run
concurrently while sharing immutable code, a scientific base, and the selected
release overlay. They do
not share Pi conversations, graph state, calculations, reports, or locks.

A Pi conversation may contain many user/assistant turns. ResearchNode completion
changes the workspace, not the transcript. A later turn learns the change from
the tool result already in context or a new context projection. Terminal mode
resumes with `--continue` or an exact `--session-id`; Phone mode selects the most
recent session by default. The launcher resolves selection before Pi opens it.
Managed in-process session replacement and fork are cancelled by Pi's
`session_before_switch` and `session_before_fork` hooks. Stop/reopen is required;
changing the active branch within the same file remains Pi's operation.

Before each Root run, the control extension appends a short package-source and
active-workspace reminder to Pi's native system prompt. It does not inject a
full workspace dump.

## Public Extensions

| Extension | Public tools and commands | Responsibility |
| --- | --- | --- |
| `ts-workflow-control` | `ts_state`, `ts_change`; `/ts`, `/ts-check` | bounded graph projection and sole canonical mutation boundary |
| `ts-workflow-review` | `ts_review`, `ts_reply` | isolated advisory Review and mandatory Root response |
| `ts-workflow-compute` | `ts_calc`, `ts_remote`; `/ts-remote` | isolated operational lifecycle over deterministic compute actions and diagnostics |
| `ts-workflow-artifacts` | `ts_seed`, `ts_compare`, `ts_import`, `ts_render`, `ts_report`, `ts_notify` | deterministic local artifacts, analyses, reports, and delivery |
| `ts-workflow-ui` | `/ts-runs` | startup, editor/footer, TS Activity, and Compute/Review history |

`ts-phone-bridge` is optional and loaded by `TSPi --standalone --phone` or a Host-owned
Worker. It forwards messages to the same Pi session and never becomes a second
scientific authority. A controller gives phone-origin turns the same Tool
authority as local TUI turns without a separate phone approval. Observer
sessions retain their read-only Tool allowlist for every turn, including local
input.

A Phone Worker restores an unresolved model only from the session's explicit
model selection, or the configured default for a new session, after awaiting
the Pi model registry refresh. It never selects an arbitrary available model.
Snapshots report a local `promptProblem` when model selection or authentication
is unavailable; a connected Bridge is not proof of model readiness.

Host-owned Workers accept messages through native Pi RPC. The Host waits for
the request-correlated prompt preflight response and consumes safe extension
error summaries from stdout. Manual TUI sessions keep the extension dispatch
path. In either mode, assistant failure and abortion remain explicit in the
Phone projection, without forwarding raw provider error bodies. This changes
neither Controller/Observer authority nor scientific workspace state.

TS Phone owns only display names, model/access preferences, lifecycle state,
and management revisions in its installation-state `management.json`. TSPi
continues to own scientific workspace files and Pi owns conversation JSONL.
Before project deletion, the Host must call TSPi's lifecycle preflight and hold
its lifecycle guard through the mutation. Unknown integrity, an occupied Root
Agent lock, active remote work, and unresolved controls block deletion. A
preflight reply is bound to the Host's resolved workspace path.

The Host coordinates activation without holding its global metadata queue
through process startup. A workspace reservation binds the requested mode and
one launch identity; only its initialized model-ready snapshot completes
startup. Preferences are saved at that point, not inferred as live authority.
An explicit source revision is required to stop an idle Host-owned runtime.
Pending prompt acknowledgements, not-yet-started inputs, tools, approvals, and
running or uncertain state block switching. Startup failure cleans up only the
owned launch. Unknown launch identities cannot reattach as external CLIs.
No prompt is automatically sent or replayed by activation. Phone event/command
receipts remain bounded and in memory; durable crash recovery is not claimed.

The shared tool catalog is an inventory and execution classification, not a
complete capability contract. Registered tool schemas define call fields;
compute capabilities define expressible adapter tasks; validation capabilities
list templates, predicates, and profiles; remote diagnostics establish live
readiness.

## Isolated Agent Runtimes

Compute and Review share the same process-level safeguards: a fresh in-memory
Pi session, inherited model identity without fallback, no parent transcript,
no Skills or package extensions, no built-in tools, no recursive delegation,
bounded task/result contracts, local validation, one structural repair, and
provider-error-first reporting. Their authority and available tools differ.

### Review

Review exists because its value depends on independent scientific reasoning.
The host:

1. selects one target Claim and asks the Context Compiler for its dependency
   snapshot;
2. creates a bounded `ts-agent-task/2` containing compact Claim, relation, Node,
   Observation, Finding, ProofSpec, ValidationResult, and a logical artifact
   manifest without paths or file contents;
3. starts a fresh Pi child session with no parent transcript, Skills,
   extensions, direct filesystem, shell, compute, mutation, or delegation;
4. enables `ts_review_result` plus, only when artifacts were selected, one
   batch-only `ts_review_artifact_read` tool; the initial turn may read once or
   submit directly, and every post-read or repair turn forces the result tool;
5. verifies path containment, size, SHA-256, Claim ownership, section and byte
   budgets before returning any excerpt, while journaling metadata but no text;
6. validates `ts-agent-result/1` locally against task identity, scope, citation
   allowlist, and advisory authority;
7. permits at most one same-session structural repair;
8. records provider failures before classifying missing or invalid output.

Provider-side strict function mode is not required. Local TypeBox and semantic
validation remain authoritative. Review cannot mutate state, create scientific
Observations, perform external effects, or accept a Claim.

Every successful Review requires exactly one deterministic
`ts_reply` before the next scientific mutation. Accepting advice
still requires primary artifacts and a normal Decision.

### Compute

`ts_calc` receives one `ts-agent-task/2` with
`role=compute`, `authority=operational`, one Node, one immutable intent digest,
and one of four closed plans:

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

Before the child starts, the host creates or resolves the intent and completes
all path, identity, digest, backend, and execution-target checks. Each child
action is a zero-argument tool bound to that preflight result. A prerequisite
must complete before a dependent action; every action can be called at most
once. `submit` and `cancel` are never replayed after an unknown effect. After a
terminal plan, the host forces `ts_compute_result`. The model supplies only
`summary` and `limitations`; the host derives all outcomes, facts, program
state, artifacts, provenance, and reconciliation flags from typed action
receipts.

## Deterministic Tool Plane

### Compute

The private compute kernel performs `prepare`, `submit`, `status`, `tail`,
`collect`, `cancel`, or `parse`. Preparation binds one ResearchNode, logical
input artifacts and roles, backend/task/parameters, execution target, and expected
outputs into an immutable `ts-calculation-intent/7`. It binds a stable
Node-contract digest and a separate scientific-intent digest. Primary Attempts
have no source; retries preserve the scientific digest; recalculations must
change it; both source relations remain inside one Node. The Kernel derives the
exact changed fields. All launches use `ts-calculation-intent/7`; older intent
schemas are unsupported and are not converted by bootstrap. The host allocates paths,
filenames, intent ID, remote directory, and submission binding.

The `local` execution target is deliberately a preparation/parsing mode: it is
valid only for `dry_run=true`, writes deterministic prepared metadata, and may
parse output files that are already present in the workspace. The kernel does
not start a local Gaussian, xTB, or scheduler process. `submit`, `status`,
`tail`, `collect`, and `cancel` require a prepared `remote` target bound to the
installation's `ts_remote` profile. This explicit split prevents a request
from appearing launchable and failing only after a model turn or a partial
side effect.

Remote transport uses OpenSSH/SCP and Torque directly. Guards distinguish
pre-effect retryable failure from an ambiguous external effect. Known job IDs
are retained even if later scheduler inspection fails. Collection follows the
immutable manifest and does not require queue history.

### Structure Seed, Comparison, And Artifact Import

`ts_seed` accepts one connected SMILES plus declared charge,
multiplicity, and `none` or `uff` initialization. The host uses fixed-seed
RDKit ETKDGv3, explicit hydrogens, charge/electron-parity checks, and optional
UFF optimization. It writes private, content-addressed XYZ and provenance files
under one open ResearchNode. The request journal stores the submitted digest,
not the SMILES body. The resulting geometry and any UFF energy are initialization
diagnostics, never stationary-point, TS, or acceptance evidence.

`ts_import` closes the empty-workspace bootstrap boundary. It accepts
bounded inline Gaussian, XYZ, or xTB control text for one open ResearchNode,
checks structure metadata and format, and writes a private content-addressed
file under the Node. Callers cannot provide a path or filename. Repeating
identical content is idempotent; conflicting or unsafe targets fail closed.
Only digest, size, format, chemical metadata, and the resulting logical
artifact are journaled, never the input body.

`ts_compare` accepts exactly two registered XYZ artifact IDs. The
host resolves their paths and digests, applies optional zero-based atom mapping,
reaction-center selection, internal-coordinate checks, explicit stereochemical
checks, and bounded RMSD thresholds, then writes a private content-addressed
JSON document below `nodes/<node_id>/outputs/analysis/`. The document binds
inputs, parameters, metrics, diagnostics, verdict, and producer provenance.
It is operational output only; the Root must register any scientific facts as
Observations through the Decision pipeline.

### Render and Report

`ts_render` validates one Node-owned input set and creates one no-overwrite local
artifact. Multi-structure comparison and mechanism outputs render each molecule
with `xyzrender`, then use a deterministic fixed-canvas compositor for panels,
captions, and reaction arrows. The public mechanism request is one ordered
reactant, transition-state, product triple. `xyzrender -l` remains reserved
for atom and bond annotations. Backend exit status, bounded stderr,
diagnostics, and command arguments remain visible in failed Activity results. `ts_report` validates the
workspace, creates a new report directory
atomically, and verifies the package manifest and file digests. Optional logical
PNG/GIF artifact IDs are re-resolved and copied into the package `assets/`
directory with an `asset_index.json`; callers never select source paths. Neither
tool uses a model or interprets chemistry.

### Notifications

`ts_notify` sends a fixed event shape to the installation-owned recipient
through configured ClawEmail. Recipient and credentials are not model fields.
`notifications.toml` is the sole recipient authority. Attachments must be exact,
unchanged members of one `ts-report-package/4` manifest. Digest-bound receipts
make known success idempotent; structured errors distinguish a delivery that did
not start from an ambiguous provider effect, which is never replayed
automatically.

## Run Journals And Result Delivery

Compute and Review journals have different scientific owners:

```text
nodes/<node_id>/attempts/<calc_id>/runs/<sub_id>/
reviews/<claim_id>/runs/<sub_id>/
```

A Compute run is part of one immutable Attempt. A Review run is advisory about
one target Claim. This ownership is enforced before journal creation; Node refs
inside a Review scope do not make the Review a Node-owned execution.

At creation, `task.json` and its bound snapshot are exclusive-created. Normal
terminal handling writes actions, optional result, and final run state. A
process crash can leave a task-only journal indexed as pending/unknown; there is
no claim of per-event write-ahead durability or automatic result replay.
If terminal journal persistence itself fails, the runtime preserves the primary
provider or action error, reports the journal failure separately, and leaves the
run pending rather than rewriting the remote action outcome.

Deterministic operations use the Activity Journal as their single activity
source of truth. Every request/status record carries `node_refs`; a shared
Activity Index validates IDs, paths, ownership, status/result consistency, and
referenced Nodes, then derives per-Node activity projections. ResearchNode records
do not duplicate activity refs and no Decision is needed to link an operation.
Compute guards and receipts remain the source for scheduler recovery; a UI or
agent-run state never proves a remote effect.

A Node cannot become terminal while an owned Compute run or deterministic
activity is non-terminal, its activity journal is inconsistent, a compute
control is pending or unresolved, or a durable calculation Attempt is awaiting
execution, collection, or parsing. The Workspace-owned lifecycle projection
contract and identity bindings are checked fail-closed without importing the
Compute host. A failed terminal scientific-input activity
may close only as `inconclusive`, `blocked`, or `stopped`. A valid terminal
`render` failure remains visible operational history but does not downgrade an
otherwise completed scientific Node. An analytical Node with no activity remains
valid.

The Attempt guard treats an intent-only or fully prepared Attempt as safe to
abandon because no external effect occurred. Every status, result, control,
Compute-run, or output record must have a valid `prepared.json` binding; a
missing or malformed preparation document is an integrity error even when a
result claims `parsed`. `failed`, `stopped`, and `parsed` are settled;
`submitted`, `queued`, `running`, `completed`, `collected`, `missing`, `unknown`,
and invalid records block completion. A control-specific pending or unresolved
record suppresses only the duplicate non-terminal state blocker; it does not
hide an independent integrity error.

The immediate tool return is the current delivery channel into the Root
conversation. `TS Activity` is presentation state and is cleared with the Pi
session. Its rows show only the live kind, semantic owner, action, state, and
elapsed time. `/ts-runs` reads durable Compute and Review summaries
on demand, uses `sub_n` as the lookup identity, and moves journal paths and files
behind the detail view's Audit section.

## Failure Semantics

- A schema, binding, or staging failure before an external effect is not an
  ambiguous submission. A typed `retry_same_submission` outcome is retryable,
  not unresolved, and does not require reconciliation.
- A missing scheduler reply after effect initiation is unknown until durable
  records or declared outputs reconcile it.
- Program failure is not automatically scientific contradiction.
- Parser failure is not automatically program failure.
- A successful deterministic action is not undone by a later UI or report-entry
  serialization error.
- Provider HTTP/stream failure outranks Compute/Review output-contract failure.
- Canonical corruption, stale revision, digest drift, cyclic graph, and partial
  bootstrap fail closed.

## Contract Locations

| Contract | Owner |
| --- | --- |
| Public tool names and execution classes | `extensions/shared/tool-catalog.ts` |
| Public call schemas | each `extensions/ts-workflow-*/index.ts` |
| Agent task/result envelopes | `packages/ts-agent-runtime/agent-core/agent-protocol.cjs` |
| Canonical scientific records | `packages/ts-agent-kernel/ts_agent/workspace/contracts/*.schema.json` |
| Decision normalization and ID allocation | `packages/ts-agent-kernel/ts_agent/workspace/decision.py` |
| Transactional mutation and validation | `packages/ts-agent-kernel/ts_agent/workspace/engine.py`, `packages/ts-agent-kernel/ts_agent/workspace/validator.py` |
| Calculation intent/result binding (dependency-neutral) | `packages/ts-agent-kernel/ts_agent/calculation_contracts.py` |
| Attempt lifecycle projection and completion guard | `packages/ts-agent-kernel/ts_agent/workspace/operational.py` |
| Public `ts_change` operation vocabulary | `packages/ts-agent-kernel/ts_agent/workspace/operation_registry.py` |
| Graph projections and Review snapshot | `packages/ts-agent-kernel/ts_agent/workspace/context.py` |
| Predicate registry and ProofSpec compiler | `packages/ts-agent-kernel/ts_agent/validation/` |
| Built-in validation policy | `packages/ts-agent-kernel/ts_agent/validation/templates/`, `packages/ts-agent-kernel/ts_agent/validation/acceptance_profiles/` |
| Compute request, intent, and result | `packages/ts-agent-kernel/ts_agent/compute/contracts/*.schema.json` |
| Backend capabilities and parsers | `packages/ts-agent-kernel/ts_agent/compute/capabilities.py`, `packages/ts-agent-kernel/ts_agent/backends/` |
| Remote lifecycle | `packages/ts-agent-kernel/ts_agent/remote/` |
| Artifact import/catalog/structure-analysis contract | `packages/ts-agent-kernel/ts_agent/compute/artifacts.py`, `packages/ts-agent-kernel/ts_agent/compute/cli.py`, `packages/ts-agent-kernel/ts_agent/structures/` |
| Render/report request/path contract | `packages/ts-agent-runtime/artifacts/request-contract.cjs` |
| Report projection | `packages/ts-agent-kernel/ts_agent/report/` |
| Read-only Web projection provider | `packages/ts-agent-kernel/ts_agent/projection/normalize.py`, `packages/ts-agent-kernel/ts_agent/projection/research_map.py`, `packages/ts-agent-kernel/ts_agent/projection/provider.py`, `scripts/ts_web_provider.py` |
| Independent Web client and UI | `components/ts-web/ts_web/`, `components/ts-web/static/`, `components/ts-web/bin/ts-web` |
| Generic atomic file IO | `packages/ts-agent-kernel/ts_agent/io.py` |
| Python distribution boundary | `pyproject.toml`, `packages/ts-agent-kernel/ts_agent/`, `scripts/_wheel.py`, release and runtime payload digests |
| Pi package/release boundary | `package.json`, `scripts/check_package.py`, installer tests |
