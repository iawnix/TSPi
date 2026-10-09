# ADR 0009: Remote Host Transport and Canonical Workspace State

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

## Status

Accepted; the SSH stream transport and terminal proxy path are implemented.

## Decision

The `tspi-host/2` NDJSON RPC is independent of its byte transport. Clients may use a private Unix
socket or start `tspi-host-proxy` over SSH, allowing the proxy to forward stdin/stdout bytes to the
remote Host Unix socket. Phone continues to use the TSPi Link WSS Relay. All three transports use
the same Host RPC and never create a second Agent lane.

```text
Client -- SSH stdin/stdout --> tspi-host-proxy -- Unix socket --> TSPi Host
```

The remote Host owns the workspace, SQLite durable sessions, Research Memory, and workspace locks
as the single canonical copy. TSPi does not use live bidirectional rsync for workspace operation.
Explicit file movement for a remote job remains an operational shell concern; artifact registration
stays separate from transport.

OpenSSH owns host-key verification, user authentication, and jump hosts; TSPi owns Host protocol
authentication and release negotiation.

## Verification

The transport covers stream framing, SSH argument validation, Host release negotiation, forwarding
for both Host and Pi App Server sockets, and cleanup when SSH or the proxy exits.
