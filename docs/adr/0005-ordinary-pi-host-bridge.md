# ADR 0005: Ordinary Pi Runtime With a Host Bridge (Retired)

[简体中文](0005-ordinary-pi-host-bridge.zh-CN.md) | English

- Status: retired; archival record only
- Date: 2026-09-21
- Scope: former launcher, Pi terminal, Host, Phone, Web, Monitor, and session-history proposal

## Decision

This ADR records a transitional design for running ordinary Pi `InteractiveMode`
behind a TSPi Host bridge. That runtime and its selector have been removed. No
`TSPI_HOST_BACKEND` selector, ordinary-runtime fallback, `tmux` persistence path,
or format-3 history importer is supported by the current code.

The current runtime uses the Native Pi Harness and the `tspi-host/2` protocol.
This ADR is retained only to explain the former design; it is not an
implementation contract. The current architecture is described in
[`ARCHITECTURE.md`](../ARCHITECTURE.md).

## Consequences

- `ResearchAgent` uses the Native Pi Harness; there is no alternate ordinary-Pi
  backend or fallback.
- Old workspace and session formats are not restored, imported, or converted.
  New installations start with new workspaces and sessions.
- The former design rationale remains available for repository history, without
  implying that its proposed runtime or migration paths exist.
