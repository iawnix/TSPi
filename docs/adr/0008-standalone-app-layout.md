# ADR 0008: Standalone Research Agent Application Layout

- Status: proposed
- Date: 2026-09-27
- Scope: installation, release activation, and client/server ownership

## Decision

Research Agent is installed as an application. Pi is a private runtime adapter,
not the installation boundary and not a public entrypoint. There is one active
release identity for the server, worker, launcher, and client handshakes.

The target layout is:

```text
/home/iaw/ResearchAgent/
  bin/ResearchAgent             # stable user CLI/TUI shim
  bin/ResearchAgentServer       # stable app-server shim
  bin/TSWeb                      # optional browser client shim
  releases/<release-id>/         # immutable application releases
  current -> releases/<release-id>
  etc/                           # configuration and owner-only secrets
  var/workspaces/                # workspace data
  var/sessions/                  # durable session metadata
  var/runtime/pi/<commit>/       # pinned Pi adapter source/runtime cache
  var/log/                       # service logs
  var/locks/                     # installation and activation locks
```

The old `.pi/packages/tspi` tree is a migration source only. No production
component may resolve an archived `ts-agent` or `tspi` release after the new
layout is activated. The stable shims resolve `current` at process start and
export the selected `release_id`; a process never mixes modules from two
release roots.

## Activation protocol

An update acquires the installation lock, marks maintenance, drains or stops
the managed App Server, atomically switches `current`, runs a release health
check, restarts the service, and clears maintenance. The service publishes the
active release ID and epoch. A TUI/Phone client whose epoch is closed receives
a reconnectable error and must attach a fresh session; it must not continue
using a stale `pi.agent-controller` binding.

## Consequences

- `ResearchAgent` is the product entrypoint; `ResearchAgentServer` is the
  control-plane process; `TSWeb` remains an optional client.
- Configuration/state/runtime/workspaces have separate ownership and backup
  boundaries.
- Pi upgrades are adapter release changes, not changes to Research Agent's
  public package identity.
- Installation tests must assert that every shim, systemd unit, worker, and
  selected package reports the same release ID and that stale archived paths
  are rejected.
