# ADR 0009: Remote Host Transport and Canonical Workspace State

## Status

Accepted; the SSH stream transport and terminal proxy path are implemented.

## Decision

The `tspi-host/1` NDJSON RPC is independent of its byte transport. Clients may use a private Unix
socket or start `tspi-host-proxy` over SSH, allowing the proxy to forward stdin/stdout bytes to the
remote Host Unix socket. Phone continues to use the TSPi Link WSS Relay. All three transports use
the same Host RPC and never create a second Agent lane.

```text
Client -- SSH stdin/stdout --> tspi-host-proxy -- Unix socket --> TSPi Host
```

The remote Host owns the workspace, SQLite durable sessions, Research Memory, and workspace locks
as the single canonical copy. TSPi does not use live bidirectional rsync for workspace operation.
A bulk copier may use the `tspi-artifact-transfer/1` manifest for bootstrap, backup, or export, but
must not copy `.pi/app-server-host/sessions` or silently replace the canonical workspace. The
manifest names every file, records whole-file and chunk SHA-256 digests, and applies files through
resumable temporary paths followed by atomic rename.

OpenSSH owns host-key verification, user authentication, and jump hosts; TSPi owns Host protocol
authentication and release negotiation. Large artifacts require a separate bounded, digest-verified,
resumable transfer contract.

## Verification

The transport covers stream framing, SSH argument validation, Host release negotiation, forwarding
for both Host and Pi App Server sockets, and cleanup when SSH or the proxy exits. Artifact transfer
tests cover manifest scope, protected paths, chunk boundaries, digest mismatches, resume, and
idempotent re-application.
