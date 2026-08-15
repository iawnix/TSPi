# Remote Execution Contract

`ts_remote` uses OpenSSH/SCP and Torque directly. There is no MCP transport in
protocol v4.

## Installation-Owned Policy

`remote.toml` owns SSH host/config, remote root, scheduler commands, queues,
resource ceilings, software commands, activation, scratch policy, and server
environment. A calculation request selects only a named profile and bounded
resources; it cannot inject host paths, commands, activation, or arbitrary env.

Use `ts_remote_inspect` for read-only diagnostics:

- `status`: SSH connectivity only;
- `doctor`: SSH, scheduler, storage, and registered software;
- `queues`: bounded queue view;
- `nodes`: bounded compute-resource view.

Ordinary startup performs no remote probe.

## Isolation

Remote directories are derived from workspace identity, ResearchAct, and
intent. The upload manifest binds regular files, sizes, SHA-256, command, profile,
resources, expected artifacts, and submission ID. Remote content is an
execution mirror, never a canonical local path.

## Control Lifecycle

Submit persists pre-effect staging state before calling Torque. Once the
scheduler request begins, transport failure may be ambiguous. Preserve any
known job ID and durable submission record even if later queue/history lookup
fails.

Cancel similarly distinguishes known no-effect, known cancellation, and
ambiguous effect. Never infer that an absent queue row means a job never ran.

Inspect may combine durable receipt, scheduler state, program status, and a
bounded declared artifact tail. Collection follows the immutable artifact
manifest and works even when scheduler history is unavailable.

## Safety

- Never submit or cancel twice after an ambiguous effect.
- Never use arbitrary remote paths or shell from Agent input.
- Never treat a healthy SSH connection as scheduler/software readiness.
- Never treat scheduler completion as program or scientific success.
- Never record remote-only content as science; collect and verify locally.
