# ADR 0004: Unified App Server Extension Runtime

[English](0004-unified-app-server-extension-runtime.md) | [简体中文](0004-unified-app-server-extension-runtime.zh-CN.md)

- Status: accepted; the retired ordinary-Pi bridge is not part of the runtime
- Date: 2026-09-17
- Scope: TSPi App Server, terminal TUI, Phone, and Web clients

## Decision

An installation-wide Pi App Server owns the Root Agent runtime, and clients
attach to its sessions. The Pi `SessionWorker`/`AgentHarness` is the runtime
owner; TSPi Host is the routing, receipt, Monitor, and Link control plane. The
terminal is Pi's official native remote client, while Phone and Monitor use
Host adapters to address the same worker lane.

Server tools are selected by `extensions/server/extensions.json` and loaded by
`apps/app-server/server-extension-loader.mjs`. Each descriptor binds a scope,
tool inventory, permissions, and a SHA-256 digest. The loader rejects paths
outside the selected Package, symbolic-link entries, unknown allowlist names,
invalid factories, and tool-name collisions with built-ins or other entries.
The App Server passes the host-owned tool context to the selected factories;
clients can only invoke the resulting protocol services.

The worker loads the digest-verified server tool facet plus package skills,
hooks, policy, and system prompt. Presentation facets remain client-side and
cannot change this worker-owned tool set.

## Provider Compatibility

Bounded Compute and Review runtimes still validate their result tool calls, but
the shared provider hook does not send a named `tool_choice` when a provider
advertises DeepSeek-style thinking mode (`thinking.type=enabled`). Those
providers reject the combination with HTTP 400. The result schema and repair
turn remain authoritative; normal non-thinking providers continue to receive
the named choice.

## Consequences

The former ordinary-Pi bridge is retained only as historical design context;
it is not packaged, selected, or reachable by this runtime.
