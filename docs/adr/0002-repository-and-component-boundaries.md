# ADR 0002: Repository And Component Boundaries

[English](0002-repository-and-component-boundaries.md) | [简体中文](0002-repository-and-component-boundaries.zh-CN.md)

- Status: accepted, implemented (Web boundary extracted; Suite `/3` retired)
- Date: 2026-09-10
- Scope: TSPi, `ts-phone`, and the optional `ts-web` component
- Related: [Architecture](../ARCHITECTURE.md), [Maintainer Guide](../MAINTAINER_GUIDE.md), [ResearchMap Design](../RESEARCH_MAP_DESIGN.md)

## Context

TSPi is currently both a product name and a repository/package boundary. The
repository contains the TSPi Skill family, Pi extensions, the Python research kernel,
deterministic compute and report services, the Web implementation, Phone
integration, release tooling, and user entrypoints. This is workable for one
release line, but it makes ownership and change cost difficult to see.

The current problems are:

1. Source libraries, user entrypoints, build tools, release artifacts, and
   runtime registration are spread across `packages/`, `apps/`, `extensions/`,
   `scripts/`, `build/`, and `dist/`.
2. `ts-phone` is already an independent repository, but the relationship
   between the TSPi product, the required core, and optional clients is not
   expressed as a simple installation contract.
3. The Web client needs an independent source and release boundary while the
   TSPi provider retains ownership of private workspace and operational data.
4. The former Phone bridge duplicated the session transport and authority
   boundary instead of using Pi's native App Server protocol.
5. Public Skill terminology and internal implementation terminology are not
   governed by one vocabulary policy.
6. The Review runtime must keep role selection, task packets, aggregation, and
   Root disposition inside one explicit advisory boundary. The source test
   entrypoint also performs a relatively expensive wheel and runtime preparation
   for ordinary Python feedback.

These are architecture and change-control problems. They should not be solved
by a broad directory move or a global terminology replacement before the
contracts are explicit.

## Confirmed Current State

| Area | Current fact | Consequence |
| --- | --- | --- |
| TSPi | Owns the kernel, Pi package, Web implementation, release assembly, and installation boundary | It is the natural required core repository and product release owner |
| `ts-phone` | Independent repository with the Flutter presentation client and mobile release tooling | It remains independently developed; its runtime dependency is the Pi App Server protocol |
| `ts-web` | Client, registry, server, and static UI under `components/ts-web/`; it consumes the canonical ResearchMap through `research-map-provider/1` | The component can be archived and installed independently from Agent |
| Phone transport | TS Phone carries Pi protocol v8 through TSPi Link; the Relay authorizes devices and forwards opaque bytes | TSPi owns the Link transport while Pi App Server remains the session authority |
| Release boundary | TSPi emits `tspi-package-release/4` with required Agent and optional independent Web descriptor | The suite contains the runtime; TS Phone is released separately |
| Review | One isolated advisory Review request accepts `reviewerRole`; the `general` role has a versioned descriptor, and a deterministic aggregator preserves individual results, failures, and disagreements | Role and aggregation contracts exist, but public execution remains one bounded request rather than parallel reviewer orchestration |
| Testing | `tools/test/runner.py` selects the manifest lane; the source lane builds a wheel and temporary overlay before running Python tests | Fast edit feedback and release-backed validation use explicit, reproducible environments |

## Decision

### 1. Product and repository identity

**TSPi** remains the product and the name of the required core repository.
The TSPi repository owns:

- the public Skill family, led by `tspi-research-kernel` for state and
  `tspi-orchestration` for task planning;
- the deterministic Research Kernel and canonical workspace contract;
- deterministic compute, artifact, report, remote, and notification mechanisms;
- the TSPi ResearchMap provider for canonical workspace data;
- core Pi extensions and lifecycle entrypoints;
- component compatibility checks, suite assembly, and installation.

`ts-phone` remains a separate repository and an optional client distribution. It
owns the mobile application, Phone-specific presentation state, deployment,
signing, and release artifacts. It does not ship a session broker or redefine
the Pi wire protocol.

`ts-web` is an optional component with its own source boundary under
`components/ts-web/`. It owns the browser UI, HTTP transport, registry client,
and thin provider client. It must not import private TSPi Python modules. TSPi
owns the ResearchMap provider, workspace paths, and provider protocol.

This distinction is deliberate:

```text
TSPi product
|
+-- TSPi Core repository             required
|     kernel, Root runtime, provider, suite installer
|
+-- ts-phone repository              optional client
|     mobile client and release tooling
|
`-- components/ts-web/                 optional component source
      ResearchMap client and browser UI
```

The product may ship one assembled release containing selected components.
Source repositories and runtime components do not need to have the same
boundary.

### 2. Component contracts

Every optional component is selected by an explicit component descriptor in
the TSPi suite manifest. The descriptor must bind, directly or through a
validated nested manifest:

```text
component_id
component_version
required_tspi_version_range
protocols
theme_or_brand_revision
capabilities
entrypoints
artifacts: path, size, digest, permissions
```

The existing `tspi-package-release/3` and component manifest contracts were the
compatibility starting point. `tspi-package-release/4` and
`tspi-package-components/4` are the authored output contracts because the Web
descriptor now names its own archive, version, protocols, and entrypoint.
The installer accepts Suite `/4` only. Previous `/3` packages must be rebuilt
from source before installation; rollback uses retained `/4` releases.

Compatibility rules:

- component semantic version, TSPi package version, and wire protocol version
  are separate values;
- a protocol major mismatch fails closed during assembly and installation;
- compatible minor and patch changes must be defined by the protocol contract,
  not guessed from package versions;
- capabilities are descriptive and cannot grant scientific mutation authority;
- an omitted Web descriptor means the component is unavailable, not silently
  embedded from a source path; TS Phone is never embedded in the suite;
- installation selects content only. Component service activation remains an
  explicit lifecycle operation.

The visual relationship between components is also versioned, but separately
from transport. TSPi owns the semantic brand/theme token contract and asset
identity. `ts-phone` and `ts-web` consume the selected theme revision or
declare a compatible fallback. A UI theme must never be encoded into a
scientific or control protocol.

### 3. Protocol ownership

Pi owns the App Server protocol and Chord service contracts. TSPi owns Link
enrollment, authorization, and opaque byte forwarding. TS Phone owns a typed
presentation adapter that maps native Pi
session, transcript, model, prompt, and abort services into its mobile UI. It
must not introduce a second broker, event journal, or semantic definition of
the App Server records.

TSPi owns the semantic source for the canonical ResearchMap consumed by Web.
The provider uses `research-map-provider/1`, while `research-map/1` is the
canonical map payload. The `/map` response contains workspace metadata plus
that direct ResearchMap serialization. It does not construct separate view and
graph models.

The minimum Web boundary is:

```text
TSPi ResearchMap provider
    -> versioned request/response contract
    -> ts-web canonical-map client and UI
```

The contract includes its protocol version, workspace metadata, the canonical
ResearchMap and its scientific revision, plus explicit error semantics. Catalog,
collection, and object-detail routes are transport conveniences over the same
map. The provider must not expose physical workspace paths or provide mutation
routes merely because the current server has local filesystem access.

Compatibility tests should run against a checked-in fixture or a released
component manifest. They must not require the two repositories to share source
imports.

### 4. Repository topology

The target topology is based on responsibility, not on flattening all
languages into one directory:

```text
TSPi/
  contracts/          versioned public schemas and compatibility fixtures
  packages/           reusable kernel/runtime libraries
  components/         independently packaged optional clients
  apps/               user-facing launchers and host entrypoints
  extensions/         Pi extension implementations
  skills/             public model-facing instructions
  tools/              build, test, release, and transition mechanisms
  docs/               architecture, operations, ADRs, and maintainer material
```

The exact package names can follow the existing Python and TypeScript build
systems. The important rules are:

- library code is not hidden in a user-facing script;
- a user entrypoint is a thin wrapper around a library or runtime;
- build and release mechanisms live under `tools/` or an explicitly named
  release package;
- public contracts live in one discoverable place and are consumed by
  validators, installers, and tests;
- `scripts/` is retained only for stable compatibility wrappers or is split
  into clearly named `apps/`, `tools/build/`, `tools/test/`, and
  `tools/release/` responsibilities.

This is a staged target, not an instruction to move the whole repository now.
The first implementation should classify and document current paths, then
move one boundary at a time while retaining stable entrypoint shims.

The first staged move places the Python kernel under
`packages/ts-agent-kernel/` and the TypeScript runtime under
`packages/ts-agent-runtime/`. The native App Server lives under `apps/`; the
terminal is Pi's client mode and TS Phone is an external TSPi Link client. Stable
package entrypoints and release manifests now point at these explicit
locations. The remaining `scripts/` transition is intentionally separate so
installed command names stay stable while mechanisms move into named tools.

### 5. Release and package metadata

The release manifest is the source of truth for a release payload. Package
manager file lists, package checks, and installers must derive from or verify
against that source rather than maintain unrelated copies of the same list.

The transition should:

1. identify required, optional, generated, and forbidden members in one
   declarative inventory;
2. make package assembly produce that inventory;
3. make package checking validate the inventory;
4. make installation consume the validated manifest;
5. keep development-only test and build files outside production archives.

The current `package.json`, `scripts/check_package.py`, and
`scripts/install_release.py` overlap in release knowledge. They should be
reduced incrementally, with a contract test that fails when their effective
payload sets diverge.

### 6. Skill terminology

The Skill vocabulary is governed by a small public glossary. Public prompts
should use the following concepts:

| Use | Meaning |
| --- | --- |
| ResearchPhase | human navigation grouping only |
| ResearchNode | one bounded research decision episode |
| Claim | scientific statement, predictions, falsifiers, and status |
| Finding | Node output, specialized as FactFinding or IssueFinding |
| Gate | common Node/Claim completion and assessment contract |
| ChangeSet | the canonical map mutation request |
| Review | bounded advisory assessment |
| Compute | bounded operational execution |

The following are implementation terms and should not become public scientific
routing concepts:

- `stage` for a private execution or failure location;
- `transaction prepare/commit` for Kernel internals;
- ad hoc gate fields used as a workflow router; evaluation belongs to the
  scoped `Gate` contract;
- `Evidence layer` or `Evidence role` when the actual owner is an Artifact or
  Finding;
- a fixed workflow stage table or a central next-action router.

This is not a global search-and-replace task. Each occurrence must be
classified as public vocabulary, private mechanism, historical compatibility,
test fixture, or documentation that intentionally describes a retired field.
Add a terminology contract test for public Skill and README surfaces before
removing compatibility fixtures.

### 7. Reviewers and subagent boundary

`packages/ts-agent-runtime/agents/review/` is the implementation location for
the isolated advisory runtime. A public request may choose `reviewerRole`; the
current package ships the versioned `general` descriptor. The runtime builds a
typed task packet for that role and records its prompt revision, inherited model
policy, artifact budget, and advisory authority.

The deterministic aggregator accepts validated reviewer results, preserves each
result and classified failure, and reports conflicting opinions without turning
them into consensus. Its contract and conflict behavior are tested. These
pieces do not imply a reviewer pool: public execution still launches one bounded
Review request, and Root must explicitly dispose of its advice before any
canonical scientific mutation.

The established reviewer contract includes:

- a versioned reviewer role descriptor;
- explicit specialty, prompt revision, model policy, artifact/result budget,
  and authority declaration;
- a deterministic typed task packet per role;
- durable per-run records for bounded execution;
- a deterministic aggregator that preserves each review and reports
  disagreement rather than hiding it;
- one explicit Root disposition before canonical scientific mutation;
- failure classification that distinguishes provider failure, invalid output,
  unavailable evidence, and reviewer disagreement.

Additional roles or parallel orchestration are separate future changes. Adding
role descriptors must not imply that independent models or providers are
available; the current role inherits the parent model and disallows override.

The following remain prohibited:

- reviewer output directly mutating canonical science;
- reviewer-selected calculation or branch execution;
- implicit consensus treated as acceptance;
- recursive reviewers or unrestricted artifact browsing;
- a process-global lock used as the only concurrency model once multiple
  reviewer roles are introduced.

### 8. Test and iteration tiers

The project adopts four feedback tiers:

| Tier | Purpose | Required behavior |
| --- | --- | --- |
| Fast | ordinary source edits | runs direct source/unit/contract checks without building a wheel or solving a runtime |
| Component | shared boundary changes | checks Python/TypeScript contracts, ResearchMap fixtures, Phone/Web compatibility, and Pi adapter behavior |
| Candidate | release-shaped validation | builds the relevant component and runs managed runtime/package tests |
| Release | delivery validation | assembles the selected suite, verifies digests/permissions, and runs end-to-end smoke checks |

Change selection should be path-aware:

- Web-only changes start with ResearchMap transport and UI checks;
- Skill-only changes start with terminology, README, and Skill contract checks;
- Review changes start with Review isolation, task/result, journal, and
  provider-recording checks;
- package or protocol changes immediately broaden to component checks;
- release and installer changes require candidate validation before delivery.

The full managed suite remains available. It is not the default command for
every edit. This preserves release confidence while reducing feedback latency
for local changes.

## Implementation Sequence

### Phase 0: freeze the boundary

- keep TSPi as the required core repository;
- keep `ts-phone` independent;
- record this ADR and link it from maintainer documentation;
- stop adding new direct Web imports of private TSPi modules;
- do not delete or move obsolete directories in this phase.

### Phase 1: establish contracts and fast feedback

- inventory public protocols, component manifests, entrypoints, and package
  members;
- add a direct fast test entrypoint;
- add manifest consistency checks;
- publish the terminology glossary and public-surface lint;
- add Phone compatibility fixtures generated from the canonical Phone source.

### Phase 2: extract the Web boundary (completed)

- expose the canonical ResearchMap behind the versioned
  `research-map-provider/1` request/response contract;
- make the Web client under `components/ts-web/` consume only that contract;
- add archive and source tests proving the client has no `ts_agent` imports;
- package the Web UI as an independently validated optional component.

### Phase 3: make optional installation explicit (completed)

- extend the existing suite manifest for optional Web and Phone descriptors;
- verify protocol, TSPi version, theme revision, capabilities, digests, and
  entrypoints during assembly and installation;
- prove that core installation works with neither optional client;
- prove that selected components can be omitted without stale symlink or
  service state. `/4` Web installs under `current/web/`.

### Phase 4: reduce directory ambiguity

- move only one responsibility at a time from `scripts/` into named tool or
  app locations;
- retain stable wrapper commands during the transition;
- move reusable code before moving its entrypoint;
- remove duplicated release lists after the manifest check is authoritative;
- keep generated artifacts out of source packages.

### Phase 5: formalize reviewer roles (partially completed)

- completed: write and validate the `general` role descriptor;
- completed: expose role selection through the existing isolated runtime;
- completed: add deterministic aggregation and disagreement fixtures;
- remaining: add bounded multi-role orchestration only if required, without
  changing the one-request advisory authority boundary.

## Non-Goals

- This ADR does not immediately split the Git repositories.
- It does not prescribe a complete rewrite of the Python kernel or Pi runtime.
- It does not make Web or Phone a second scientific state owner.
- It does not replace open scientific vocabulary with closed enums.
- It does not rename every internal `stage` field or historical fixture.
- It does not add multiple model providers merely to create the appearance of
  reviewer independence.
- It does not create a separate Git repository for `ts-web`; the component
  source boundary is currently maintained in `components/ts-web/`.

## Acceptance Criteria

The restructuring is ready for implementation completion only when:

- TSPi core starts and tests without `ts-phone` and `ts-web`;
- optional components are selected through a validated manifest, not source
  path discovery;
- Phone schemas have one canonical source and TSPi has compatibility tests;
- Web communicates through a versioned read-only ResearchMap transport and has no private
  `ts_agent` imports;
- protocol, component, and theme revisions are visible in diagnostics and
  checked during assembly;
- release membership is derived from one inventory;
- public Skill terminology passes a dedicated contract test;
- a reviewer role can run, fail, disagree, and report without mutating
  canonical science;
- fast checks avoid wheel/runtime preparation while candidate and release checks
  retain the managed runtime boundary;
- obsolete residue is removed only in a separately authorized cleanup change.

## Consequences

This decision adds explicit component manifests, ResearchMap contracts, and
compatibility tests. It also requires maintainers to distinguish source
ownership from release assembly and public terminology from private mechanics.

The benefit is that TSPi can remain one coherent product while its Phone and
Web clients evolve independently. A component can be omitted, upgraded, or
rejected for incompatibility without changing scientific state ownership. The
cost is an initial contract and transition phase before directory cleanup
produces visible results.
