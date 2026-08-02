# TS Cluster MCP

The bundled `cluster_mcp` package is the cluster-side execution boundary. It
uses MCP Python SDK `2.0.0` and supports OpenPBS or Torque. It does not decide
chemistry, register evidence, mutate canonical TS workspace state, or imply
that a completed program supports a hypothesis.

## Deployment Boundary

Run the server on the cluster or behind a protected cluster gateway. Keep the
Pi research workspace and all canonical state local. The cluster workspace is
an execution mirror owned by one authenticated MCP principal.

Install a dedicated environment from the repository checkout rather than a Pi
package cache:

```bash
conda env create -p /path/to/ts-cluster-mcp-env -f environment.yml
cp cluster_mcp/config.example.toml /private/path/config.toml
cp cluster_mcp/auth.example.toml /private/path/auth.toml
chmod 600 /private/path/auth.toml
```

For a loopback HTTP listener reached through an SSH tunnel:

```bash
export CLUSTER_MCP_HTTP_TOKEN='<at-least-32-random-ascii-characters>'
/path/to/ts-cluster-mcp-env/bin/python scripts/ts_cluster_mcp.py serve \
  --config /private/path/config.toml \
  --transport streamable-http
```

Non-loopback listeners require TLS and a direct-client network allowlist.
Bearer tokens, TLS keys, auth files, and runtime databases must not be tracked.

## TS Tools

- `ts_ensure_directory`: idempotently create a principal-owned execution tree.
- `ts_prepare_upload`: start a bounded upload or replay an exact existing file.
- `upload_chunk`, `finish_upload`, `abort_upload`: transfer one digest-bound
  file without overwrite.
- `ts_submit_job`: submit one `ts-cluster-job/1` request exactly once per
  `submission_id`.
- `ts_get_submission`: return the durable submission record and normalized
  scheduler state.
- `download_chunk`: retrieve an artifact for local verification.
- `ts_cancel_submission`: cancel only the job bound to the principal,
  `submission_id`, and exact `submission_id:job_id` confirmation.

The Pi principal should receive only `cluster:read`, `files:read`,
`files:write`, `ts:read`, `ts:submit`, and `ts:control`. Do not grant it generic
`jobs:submit` or `jobs:control`; those scopes expose the reference server's
administrative script and software tools. `files:write` is no-overwrite;
generic replacement requires the separate `files:overwrite` scope, which the
Pi principal must not receive.

## Submission Contract

`ts-cluster-job/1` binds:

- `submission_id`, `intent_id`, `intent_digest`, `node_id`, and backend;
- a workspace-relative execution directory and script;
- every input path, size, and SHA-256 digest;
- every expected artifact path;
- the complete queue, resources, environment, and GPU-device request.

The server stores this request before `qsub`. An identical submitted request is
replayed without another scheduler call. Reusing a `submission_id` with changed
content is rejected. A scheduler ID is persisted immediately after a successful
`qsub`, before secondary ownership and audit writes. Any exception after
entering submission is recorded as `ambiguous`; automatic resubmission is
forbidden because a timeout may hide a successful `qsub`.

Cancellation first reserves the submission as `cancelling`. A `qdel` timeout
becomes `cancellation_ambiguous`, and the server refuses automatic replay. A
known job from a post-`qsub` persistence failure can still be cancelled only
with its exact `submission_id:job_id` binding.

Program and scheduler records remain operational facts. Downloaded artifacts
must be verified locally, parsed deterministically, and registered through a
later `ts_workspace` decision before they become evidence.

## Pi Host Boundary

`ts_remote.mcp` is the host-side MCP client. It validates HTTPS or loopback
transport, keeps bearer tokens in environment variables, performs chunked
digest-bound uploads, binds downloads to a server-side SHA-256 descriptor, and
returns node/intent-bound receipts. Raw cluster
MCP tools are not registered in the Pi Root Agent or child-agent inventories.

Submission and cancellation still require a separate current-turn host
authorization design before Pi public tools may expose them. The presence of
the MCP client and server is not authorization to perform external side
effects.
