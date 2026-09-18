# Maintainer Guide

TSPi is a Pi package with a native App Server launcher. Keep the package
boundaries explicit: App Server owns sessions, the Python kernel owns
scientific state, and optional TS Web only reads workspaces.

## Development Setup

Install the pinned Pi source and the scientific environment described by
`environment.yml`. Run the fast test suite before changing package layout:

```bash
python3 tools/test/runner.py fast -- -q
npm run lint:public
```

The full suite uses `python3 tools/test/runner.py source -- -q`. Use
`python3 tools/test/runner.py list` to inspect all lanes. Native App Server
checks use `npm run test:native-pi` and require `TSPI_PI_SOURCE` pointing at the
prepared Pi checkout. Remote smoke and live model evaluation are opt-in lanes;
they require explicit external configuration and are never part of the default
suite.

The authoritative lane and path definition is `tools/test/manifest.toml`,
dispatched by `tools/test/runner.py`. Python tests are grouped under
`tests/unit/`, `tests/contract/`, and `tests/integration/`; Node tests live under
`tests/node/`; shared fixtures are under `tests/support/`. External probes and
live scenarios belong to `tools/test/probes/` and `tools/test/scenarios/` and
must not be added to the default Python suite.

## Scientific Model

The canonical workspace files are `workspace.json`, `research_map.json`, and
`transactions.jsonl`. `ResearchMap` owns phases, claims, claim relations,
nodes, typed findings, gates, focus, and revision. Node execution records live
under `nodes/<node_id>/` and are operational inputs to the map, not alternate
scientific registries.

## ResearchMap Validation Rules

Validation is deterministic and revision-bound. Gates evaluate declared map
criteria and evidence references; Root Agent interpretation changes Claim or
Node state through a ResearchMap ChangeSet. Unsupported legacy files are
rejected explicitly during bootstrap.

## Deterministic Tool Contracts

Backend adapters live in `packages/ts-agent-kernel/ts_agent/backends/` and must
parse only their own formats. Every artifact gets a content digest and a safe
workspace-relative path. Remote jobs record scheduler, job ID, command, and
retrieval outcome without overwriting earlier evidence.

## Scientific Analysis Maintenance

Independent analyses use the closed ID/version registry in `analysis/catalog.py`
and handler dispatch in `analysis/engine.py`. New scientific algorithms require
bounded inputs, explicit applicability, counterexamples, replayable candidates
and a version change when deterministic output semantics change. Keep domain
schemas out of the always-loaded tools. Do not add scientific successor routing.

Node pause/resume receipts are operational state. Preserve the shared workspace
lock at submission and analysis boundaries; keep inspection, collection and
cancellation available. Test native App Server and extension entrypoints, wheel
installation, direct ResearchMap Web rendering and source-tampering rejection. Use the stable
operations guide and focused test suites as the current evidence; one-off
validation reports do not belong in the repository.

## Documentation Ownership

- `docs/ARCHITECTURE.md` — runtime and scientific boundaries.
- `docs/INSTALLATION.md` — installer, services, upgrades, and recovery.
- `docs/TERMINAL.md` — native TUI/App Server usage.
- `skills/` — user-facing scientific procedures and references.
- `contracts/ts-web/` — optional browser transport schemas for canonical map responses.

TS Phone documentation and mobile release tooling are maintained in the
independent `ts-phone` repository. TSPi must not reintroduce a Phone server,
bridge, REST/SSE compatibility layer, or terminal Host.

## Contract Change Matrix

| Change | Required updates |
| --- | --- |
| App Server protocol or service | `apps/app-server/`, launcher tests, TS Phone client, architecture docs |
| Workspace schema | kernel contract, bootstrap, validation tests, workspace references |
| Scientific backend | backend parser, capability registry, focused skill reference, tests |
| Scientific analysis | analysis registry/handler, replay validation, scientific counterexamples, report/Web transport, wheel inventory |
| Node dispatch | operational receipt chain, submission guard, native/extension tools, restart and pause tests |
| Package inventory | `package.json`, `scripts/package_inventory.py`, package layout tests |
| Installer/service path | `scripts/install_wizard.py`, uninstall logic, installation docs |

## Release Procedure

1. Run the fast and full Python suites plus native App Server tests.
2. Build and validate the Agent release with `npm run release:agent`.
3. Build the optional Web component when requested by the release plan.
4. Build the suite package with `npm run release:build` and inspect its manifest.
5. Test installation into a fresh private directory and start one installation Host.

The package manifest, archive digest, selected Agent component, and Pi source
commit must agree. Never publish a dirty source tree or modify a release after
it has been content-addressed.

## Rollback Discipline

Stop the Host service, select a prior validated release under
`.pi/packages/tspi/releases`, and restart the single Host. Workspace JSONL and
scientific records are independent of the package release and must not be
deleted during rollback.
