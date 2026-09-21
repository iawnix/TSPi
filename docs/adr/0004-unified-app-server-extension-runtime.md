# ADR 0004: Unified App Server Extension Runtime

[English](0004-unified-app-server-extension-runtime.md) | [简体中文](0004-unified-app-server-extension-runtime.zh-CN.md)

- Status: accepted
- Date: 2026-09-17
- Scope: TSPi App Server, terminal TUI, Phone, and Web clients

## Decision

The installation-wide systemd App Server is the only production Root Agent
runtime. Clients attach to its sessions; they do not start a second workflow
runtime or upload executable extensions. The terminal command
`TSPi --workspace <name>` remains a Pi client and therefore keeps Pi's client
TUI. With a configured user or system service, the launcher starts that service
when its Host socket is absent and waits for the same installation Host; it
never starts a second foreground Host. With service scope `none`, the managed
Host is disabled; configure a user or system service before opening a workspace.

Server tools are selected by `extensions/server/extensions.json` and loaded by
`apps/app-server/server-extension-loader.mjs`. Each descriptor binds a scope,
tool inventory, permissions, and a SHA-256 digest. The loader rejects paths
outside the selected Package, symbolic-link entries, unknown allowlist names,
invalid factories, and tool-name collisions with built-ins or other entries.
The App Server passes the host-owned tool context to the selected factories;
clients can only invoke the resulting protocol services.

The `tspi-server-tools` entry is the canonical server tool set. Its
implementation is shared by all attached clients. The legacy Pi presentation
extensions remain available for direct `pi` compatibility. TSPi's presentation
facet is selected by the launcher and delivered to Pi's native remote client
through the server-produced facet bundle. It may contribute layout components
and slash commands, but Pi's client TUI remains the owner of input, completion,
selectors, transcript rendering, and busy-state handling. New workflow
functionality must add one server entry and use the shared command surface
instead of adding a per-client broker.

## Provider Compatibility

Bounded Compute and Review runtimes still validate their result tool calls, but
the shared provider hook does not send a named `tool_choice` when a provider
advertises DeepSeek-style thinking mode (`thinking.type=enabled`). Those
providers reject the combination with HTTP 400. The result schema and repair
turn remain authoritative; normal non-thinking providers continue to receive
the named choice.

## Consequences

- One session transcript and one Root lock are shared by TUI, Phone, and Web.
- A disconnected TUI can be replaced by another authenticated client without
  replaying an uncertain prompt or remote action.
- Package release validation includes the loader, manifest, and server entry,
  so a service cannot silently run an unvalidated extension.
