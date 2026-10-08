# Maintainer Guide

TSPi is a Pi package with an installation Host and a native Pi client launcher.
Keep the package boundaries explicit: the Pi Harness worker owns sessions and
turns, Host owns routing and receipts, the Python Research State runtime owns scientific state,
and optional TS Web only reads workspaces. The Node side exposes only the
Research State transport bridge and port; it has no alternate Research State filesystem boundary
implementation.

## Development Setup

Install the pinned Pi source and the scientific environment described by
`environment.yml`. Run the fast test suite before changing package layout:

```bash
python3 tools/test/runner.py fast -- -q
npm run lint:public
```

The full suite uses `python3 tools/test/runner.py source -- -q`. Use
`python3 tools/test/runner.py list` to inspect all lanes. The native lane
exercises the Harness Host, native Pi client, history isolation/import, Monitor
delivery, TSPi Link, and the pinned Pi extension/provider boundaries. Run it with
a prepared checkout
whose commit matches `config/pi-source.json`:

```bash
export TSPI_TEST_PI_RUNTIME_ROOT=/path/to/prepared/pi
npm run test:native-pi
```

The Native Pi Harness path does not require tmux and is the only supported
runtime. `TSPI_HOST_BACKEND=ordinary` and `TSPI_TMUX` are rejected. Do not
substitute an unpinned or modified Pi checkout to make the lane pass. Remote smoke and live
model evaluation are opt-in lanes; they require explicit external configuration
and are never part of the default suite.

The authoritative lane and path definition is `tools/test/manifest.toml`,
dispatched by `tools/test/runner.py`. Python tests are grouped under
`tests/unit/`, `tests/contract/`, and `tests/integration/`; Node tests live under
`tests/node/`; shared fixtures are under `tests/support/`. External probes and
live scenarios belong to `tools/test/probes/` and `tools/test/scenarios/` and
must not be added to the default Python suite.

## Scientific Model

The canonical workspace identity is `workspace_manifest.json`. Research
workspaces store scientific state in `research_map/context.json`, lifecycle in
`lifecycle/liveness.json`, and the Research State-owned metadata projection in
`memory/index.json`. The canonical JSON records include phases, claims, claim
relations, nodes, findings, gates, requirements, Attempts, Artifacts, focus,
and revision. Research State contracts and ChangeSets validate these records;
`research.map` supplies the client projection. Job inputs, logs, and receipts
live under `runs/jobs/<job_id>/`; registered payloads live under `artifacts/`.
Retired `workspace.json`, `research_map.json`, and
`transactions.jsonl` files are not runtime authorities.

## ResearchMap Validation Rules

Validation is deterministic and revision-bound. Gates evaluate declared map
criteria and evidence references; Root Agent interpretation changes Claim or
Node state through a ResearchMap ChangeSet. Unsupported legacy files are
rejected explicitly during bootstrap.

## Deterministic Tool Contracts

Scientific command builders and parsers live in
`extensions/chemical/skills/<skill>/scripts/`, with shared helpers in
`extensions/chemical/skills/_shared/`. Generic local and remote execution lives
in `packages/job-runtime/`; `packages/tspi-runtime/` binds Job receipts and
collected Artifacts to Research State. Public command fields are declared in
`packages/tspi-runtime/tspi_runtime/command_catalog.json`. Every Artifact needs
a content digest and a verified location. Preserve earlier evidence when
recording scheduler state, Job identity, commands, and collection results.

## Scientific Analysis Maintenance

Independent analyses run Skill scripts through generic Jobs. Registered
validators and acceptance profiles are declared in the extension manifest;
`packages/tspi-runtime/tspi_runtime/validators.py` verifies and stages the
declared validator and inputs. The extension manifest contract lives in
`contracts/tspi-extension/1/`. Provider metadata discovery remains supported,
but does not dispatch scientific execution. New scientific algorithms require
bounded inputs, explicit applicability, counterexamples, replayable candidates
and a version change when deterministic output semantics change. Keep domain
schemas out of the always-loaded tools. Do not add scientific successor routing.

Node state and dependency admission belong to Research State. Preserve the
workspace transaction boundary around dispatch intentions, execution observations,
and collected evidence; keep inspection, collection and cancellation available.
Test the Native Harness client and server-extension contract,
Monitor retry/acknowledgement behavior, wheel
installation, direct ResearchMap Web rendering, and source-tampering rejection.
Use the stable operations guide and focused test suites as the current evidence;
one-off validation reports do not belong in the repository.

## Documentation Ownership

- `docs/ARCHITECTURE.md` — runtime and scientific boundaries.
- `docs/INSTALLATION.md` — installer, services, upgrades, and recovery.
- `docs/TERMINAL.md` — Native Pi TUI, Host, Phone, and Monitor usage.
- `extensions/*/skills/` — user-facing scientific procedures and references.
- `contracts/ts-web/` — optional browser transport schemas for canonical map responses.

TS Phone documentation and mobile release tooling are maintained in the
independent `ts-phone` repository. TSPi owns the small authenticated Host bridge
and optional browser gateway; it must not add a second Pi renderer, Phone
broker, or alternate session owner.

## Contract Change Matrix

| Change | Required updates |
| --- | --- |
| TSPi Host protocol or service | `apps/app-server/`, launcher tests, TS Phone client, architecture docs |
| Workspace schema | Research State runtime contract, bootstrap, validation tests, workspace references |
| Scientific software | Skill scripts/parsers, environment configuration, focused Skill references, tests |
| Scientific analysis | script, validator/profile manifest when applicable, input and output validation, scientific counterexamples, extension resource digests |
| Node and Job admission | Research State admission/dependencies, dispatch and receipt transactions, native tools, restart and reconciliation tests |
| Package inventory | `package.json`, `scripts/package_inventory.py`, package layout tests |
| Installer/service path | `scripts/install_wizard.py`, uninstall logic, installation docs |

## Release Procedure

1. Run the fast and full Python suites plus the native Harness/Host lane.
2. Build and validate the Agent release with `npm run release:agent`.
3. Build the optional Web component when requested by the release plan.
4. Build the suite package with `npm run release:build` and inspect its manifest.
5. Test installation into a fresh private directory and start one installation Host.

The package manifest, archive digest, selected Agent component, and Pi source
commit must agree. Never publish a dirty source tree or modify a release after
it has been content-addressed.

## Rollback Discipline

Stop the Host service, select a prior validated release under
`releases`, and restart the single Host. Workspace JSONL and
scientific records are independent of the package release and must not be
deleted during rollback.
