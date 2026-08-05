# TS Cluster MCP

The bundled `cluster_mcp` package is the cluster-side execution boundary. It
uses MCP Python SDK `2.0.0` and supports OpenPBS or Torque. It does not decide
chemistry, register evidence, mutate canonical TS workspace state, or imply
that a completed program supports a hypothesis.

## Contents

- [Deployment model](#deployment-model)
- [Prerequisites](#prerequisites)
- [Install the server environment](#install-the-server-environment)
- [Configure the server](#configure-the-server)
- [Create the bearer token](#create-the-bearer-token)
- [Run the preflight check](#run-the-preflight-check)
- [Start the server in the foreground](#start-the-server-in-the-foreground)
- [Connect through an SSH tunnel](#connect-through-an-ssh-tunnel)
- [Use direct HTTPS](#use-direct-https)
- [Verify the Pi client](#verify-the-pi-client)
- [Run under systemd](#run-under-systemd)
- [Troubleshooting](#troubleshooting)
- [TS tools and authority](#ts-tools-and-authority)

## Deployment Model

Run the server on the cluster login node or a protected cluster gateway. Keep
the Pi research workspace and all canonical state on the Pi host. The cluster
workspace is an execution mirror owned by one authenticated MCP principal.

The recommended first deployment is:

```text
Pi host -> local 127.0.0.1:8765 -> SSH tunnel -> cluster 127.0.0.1:8765
```

This keeps the MCP listener off the cluster network. Use direct HTTPS only when
the site permits a network listener and its firewall, certificate, and client
allowlist are maintained.

The server checkout and environment are separate from both the Pi package
checkout and the Pi workspace-owned runtime. Updating or reinstalling the Pi
package must not delete the cluster service environment, configuration,
workspace, or databases.

## Prerequisites

Use a non-root cluster account that:

- is recognized by the scheduler and is allowed to query and submit jobs;
- can execute the configured `qstat`, `qsub`, `qdel`, and related PBS commands;
- owns the MCP workspace, private configuration, authentication registry, and
  runtime databases;
- has access to the software activation scripts and queues used by TS jobs.

Every job submitted by this service is an operating-system job owned by the
server account. Do not run the service as `root`. A shared service account is
appropriate only when cluster policy explicitly allows it; otherwise run one
service instance as the researcher's normal PBS account.

Determine the scheduler implementation before editing the configuration:

```bash
/opt/pbs/bin/qstat --version
```

Use `scheduler.backend = "openpbs"` only when the installed commands support
the JSON forms used by this server, including `qstat -Qf -F json`. Use
`scheduler.backend = "torque"` for legacy Torque/PBS commands without OpenPBS
JSON output. The Torque backend does not support OpenPBS placement directives,
host pinning, GPU resource syntax, or historical `qstat -x` queries.

The examples assume an existing repository checkout on the cluster. Pin the
checkout to the same tested branch or release as the Pi package rather than
running a moving default branch.

## Install the Server Environment

From the cluster checkout, create a dedicated Conda environment. Do not install
the MCP dependencies into Conda `base` or reuse a Pi workspace runtime:

```bash
export REPO_ROOT=/absolute/path/to/TSAgentSkill
export MCP_ENV=/absolute/path/to/ts-cluster-mcp-env
conda env create --prefix "$MCP_ENV" --file "$REPO_ROOT/environment.yml"
```

The server is launched through the checkout entrypoint, so no global
`cluster-mcp` executable is required. Verify the CLI from any directory:

```bash
"$MCP_ENV/bin/python" "$REPO_ROOT/scripts/ts_cluster_mcp.py" --help
```

Create private configuration and workspace directories owned by the server
account:

```bash
export MCP_CONFIG_DIR=/absolute/private/path/ts-cluster-mcp
export MCP_WORKSPACE=/absolute/path/to/cluster-mcp-workspaces
install -d -m 700 "$MCP_CONFIG_DIR" "$MCP_WORKSPACE"
cp "$REPO_ROOT/cluster_mcp/config.example.toml" "$MCP_CONFIG_DIR/config.toml"
cp "$REPO_ROOT/cluster_mcp/auth.example.toml" "$MCP_CONFIG_DIR/auth.toml"
chmod 600 "$MCP_CONFIG_DIR/config.toml" "$MCP_CONFIG_DIR/auth.toml"
```

`auth.toml` must be a regular non-symlink file, owned by the server user, with
mode `0600`. The server rejects a registry owned by another user or readable by
the group or other users.

## Configure the Server

Edit the copied `config.toml`; do not edit or track the example file with site
paths. At minimum, set:

- `workspace.root` to the server-owned execution mirror root;
- `audit.path` beneath a private server-owned directory;
- `auth.principals_file` to the absolute private `auth.toml` path;
- `scheduler.backend` to `openpbs` or `torque`;
- `scheduler.allowed_queues` and `scheduler.gpu_queues` to site-valid queues;
- every `scheduler.commands` value to the actual absolute PBS executable;
- `http.principal` to the principal declared in `auth.toml`.

For the recommended SSH-tunnel deployment, keep:

```toml
[http]
host = "127.0.0.1"
port = 8765
path = "/mcp"
public_url = "http://127.0.0.1:8765/mcp"
principal = "pi-ts"
token_env_var = "CLUSTER_MCP_HTTP_TOKEN"
allowed_client_networks = ["127.0.0.1/32", "::1/128"]
stateless = true
json_response = true
```

The `public_url` path must exactly match `http.path`. Keep the same host and
port in the SSH tunnel and Pi endpoint because MCP transport security validates
the HTTP `Host` value against `public_url`.

The matching Pi principal in `auth.toml` should have only:

```toml
[principals.pi-ts]
enabled = true
scopes = [
  "cluster:read",
  "files:read",
  "files:write",
  "ts:read",
  "ts:submit",
  "ts:control",
]
workspace_prefix = "pi-ts"
```

Do not grant the Pi principal `admin`, `jobs:submit`, `jobs:control`, or
`files:overwrite`. `files:write` is intentionally no-overwrite. The
`workspace_prefix` must be a safe relative path and gives the principal a
private subtree beneath `workspace.root`.

Set `scheduler.allow_submission` or `scheduler.allow_job_control` to `false`
when the site wants a read/transfer-only deployment. These server switches and
the principal scopes are both enforced.

## Create the Bearer Token

Generate one random token on the cluster and keep it outside the repository:

```bash
umask 077
printf 'CLUSTER_MCP_HTTP_TOKEN=%s\n' "$(openssl rand -hex 32)" \
  > "$MCP_CONFIG_DIR/cluster-mcp.env"
chmod 600 "$MCP_CONFIG_DIR/cluster-mcp.env"
```

The token must contain at least 32 non-whitespace ASCII characters. The two
environment variable names are different, but their secret value is identical:

| Side | Variable | Value |
|---|---|---|
| Cluster server | `CLUSTER_MCP_HTTP_TOKEN` | generated bearer secret |
| Pi client | `TS_CLUSTER_MCP_TOKEN` | the same bearer secret |

Transfer the value to the Pi host through the site's approved secret channel.
Do not put it in `config.toml`, calculation intents, shell scripts, task
packets, logs, or tracked files.

## Run the Preflight Check

Run the server-side preflight as the exact operating-system account that will
run the service:

```bash
"$MCP_ENV/bin/python" "$REPO_ROOT/scripts/ts_cluster_mcp.py" check \
  --config "$MCP_CONFIG_DIR/config.toml"
```

The underlying CLI operation is `cluster-mcp check`. It validates the TOML and
authentication registry, creates missing private workspace metadata and SQLite
stores, verifies configured command paths, and performs read-only scheduler
queries. It does not call `qsub` or `qdel`.

Review the JSON result for:

- `workspace.exists = true` and `workspace.writable = true`;
- scheduler command paths with `exists = true` and `executable = true`;
- an empty `scheduler.missing_allowed_queues` list;
- the expected `scheduler.backend` and visible queues.

`check` does not load the HTTP bearer token or open the HTTP listener. The
foreground start and Pi smoke test below verify transport authentication. Do
not use a manual `qsub` as a connectivity test.

## Start the Server in the Foreground

Load the private server environment and start Streamable HTTP:

```bash
set -a
. "$MCP_CONFIG_DIR/cluster-mcp.env"
set +a
"$MCP_ENV/bin/python" "$REPO_ROOT/scripts/ts_cluster_mcp.py" serve \
  --config "$MCP_CONFIG_DIR/config.toml" \
  --transport streamable-http
```

For the tunnel configuration, confirm that it listens only on
`127.0.0.1:8765`. Keep this foreground process running while performing the
client smoke test. A successful server start validates the token, HTTP
configuration, authentication principal, and any configured TLS files.

## Connect Through an SSH Tunnel

On the Pi host, open a second terminal and create the tunnel:

```bash
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 cluster-login
```

`cluster-login` may be an SSH config alias. The first address is local to the
Pi host; the second is the loopback listener on the cluster host. Do not add
`0.0.0.0` or `-g`, which would expose the local end of the tunnel.

Configure the Pi process in the same shell or service environment used to
launch Pi:

```bash
export TS_CLUSTER_MCP_URL=http://127.0.0.1:8765/mcp
export TS_CLUSTER_MCP_TOKEN='<same value as server CLUSTER_MCP_HTTP_TOKEN>'
export TS_CLUSTER_MCP_TIMEOUT=60
```

The tunnel authenticates the SSH connection; MCP still requires its bearer
token and principal scopes. After exact intent binding and a read-only
capability preflight, the Root Agent may submit or cancel through the scoped
compute operator without an additional Pi UI confirmation.

## Use Direct HTTPS

For a site-approved direct listener, configure the built-in TLS server with a
real DNS name and restrict direct client addresses:

```toml
[http]
host = "0.0.0.0"
port = 8765
path = "/mcp"
public_url = "https://cluster.example:8765/mcp"
principal = "pi-ts"
token_env_var = "CLUSTER_MCP_HTTP_TOKEN"
allowed_client_networks = ["203.0.113.10/32"]
tls_cert_file = "/absolute/path/to/server-chain.pem"
tls_key_file = "/absolute/private/path/to/server-key.pem"
stateless = true
json_response = true
```

A non-loopback listener is rejected unless TLS and a non-empty network
allowlist are configured. The private key must be a regular file owned by the
server user with mode `0600`; the certificate must be a readable regular file.
Open only the required port in the site firewall.

The allowlist checks the direct TCP peer. `X-Forwarded-For` and other forwarded
headers are not trusted. When a reverse proxy is used, the allowlist therefore
sees the proxy address, and proxy/TLS/Host behavior must be validated as a
separate site deployment. On the Pi host use:

```bash
export TS_CLUSTER_MCP_URL=https://cluster.example:8765/mcp
export TS_CLUSTER_MCP_TOKEN='<same value as server CLUSTER_MCP_HTTP_TOKEN>'
export TS_CLUSTER_MCP_TIMEOUT=60
```

The Pi client rejects non-loopback plain HTTP endpoints.

## Verify the Pi Client

Use the installed Pi workspace runtime, not an unrelated system Python. Resolve
the interpreter from the runtime manifest:

```bash
export TS_AGENT_SKILL_ROOT=/absolute/path/to/pi/package/TSAgentSkill
export TS_WORKSPACE_ROOT=/absolute/path/to/ts-workspace
export RUNTIME_PYTHON="$(
  python "$TS_AGENT_SKILL_ROOT/scripts/ts_runtime.py" resolve \
    --workspace-root "$TS_WORKSPACE_ROOT" --json |
  python -c 'import json, sys; print(json.load(sys.stdin)["python_executable"])'
)"
```

With the SSH tunnel or HTTPS endpoint active and all `TS_CLUSTER_MCP_*`
variables exported, run the packaged read-only diagnostic through the Pi
workspace runtime. Its `status` and `doctor` modes call only
`cluster_capabilities`:

```bash
PYTHONPATH="$TS_AGENT_SKILL_ROOT" "$RUNTIME_PYTHON" \
  "$TS_AGENT_SKILL_ROOT/scripts/ts_compute.py" mcp-diagnostic --mode doctor
```

The result should report `server = cluster-mcp`, the expected scheduler,
principal `pi-ts`, workspace prefix, queue allowlist, and TS scopes. This smoke
test does not submit, cancel, upload, overwrite, or register scientific
evidence. Start Pi from the same environment after it passes, then use
`/ts-mcp cluster` for a combined capability, queue, and node view, or
`/ts-mcp status|queues|nodes` for narrower user-facing checks. The combined view
contains aggregate queue and node resource counts, not raw per-node job lists.
Use it only for the configured MCP target. Follow the calculation intent's
transport or the user's explicit target, and never switch to SSH automatically
after an MCP failure. Reports that compare transports must identify the source
of each result. The Agent sees the read-only `ts_mcp_inspect` tool
registration without receiving an MCP report on every turn.

## Run Under systemd

After foreground verification, a site administrator can install a system
service. Replace every placeholder with an absolute path:

```ini
[Unit]
Description=TS Cluster MCP
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ts-mcp
Group=ts-mcp
WorkingDirectory=/absolute/path/to/TSAgentSkill
EnvironmentFile=/absolute/private/path/ts-cluster-mcp/cluster-mcp.env
ExecStart=/absolute/path/to/ts-cluster-mcp-env/bin/python /absolute/path/to/TSAgentSkill/scripts/ts_cluster_mcp.py serve --config /absolute/private/path/ts-cluster-mcp/config.toml --transport streamable-http
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`User` and `Group` must identify the PBS account chosen during setup, not
`root`. That user must own `auth.toml`, `cluster-mcp.env`, the TLS private key
when present, and the MCP workspace. It must also be able to traverse the
checkout and environment paths. If the cluster permits persistent user
services, the same `ExecStart`, `EnvironmentFile`, and `UMask` can be used in a
user unit without `User` or `Group`.

Run `check` manually before every service restart. Then use the site's systemd
workflow to reload, enable, and start the unit, and inspect both service status
and journal output. Repeat the read-only Pi capabilities smoke test after the
service starts.

## Troubleshooting

### `Authentication configuration permissions must be 0600`

Run `chown` as the site administrator if ownership is wrong, then run
`chmod 600 auth.toml`. Do not replace the file with a symlink.

### HTTP token missing, short, or rejected

Confirm that the service loaded `cluster-mcp.env`, that the variable name
matches `http.token_env_var`, and that `TS_CLUSTER_MCP_TOKEN` contains the exact
same secret value. Do not print the token into logs while diagnosing it.

### HTTP 401 or client authentication failure

The bearer token is missing or different, `http.principal` does not match an
enabled `auth.toml` principal, or the registry changed after the client
connected. Correct the server and client settings, restart the server, and
reconnect.

### HTTP 403 `client_network_denied`

The direct peer address is outside `http.allowed_client_networks`. For an SSH
tunnel, retain the loopback entries. For direct HTTPS, add only the Pi host or
approved proxy network; forwarded headers do not affect this check.

### Connection refused through the tunnel

Confirm that the cluster process is running on `127.0.0.1:8765`, the SSH
tunnel is still active, and no local process already owns port 8765. The local
URL, tunnel ports, and configured `public_url` authority must agree.

### TLS or `public_url` validation fails

Set both TLS files or neither, use `https` exactly when TLS files are present,
and make the `public_url` path exactly equal to `http.path`. Ensure the private
key is server-user-owned mode `0600` and all parent directories are
traversable by the service account.

### OpenPBS returns malformed JSON

The configured commands may belong to Torque or an older PBS implementation.
Set `scheduler.backend = "torque"` when appropriate, or point the OpenPBS
backend at commands that support the required JSON options. Do not work around
the error by parsing scheduler text in the MCP client.

### Commands or queues fail `check`

Use absolute executable paths, run `check` as the service account, and verify
that the same account can perform read-only queue queries. Correct
`allowed_queues`; do not submit a probe job merely to validate installation.

### Submission or cancellation is ambiguous

Do not retry automatically with the same or a new identifier. Inspect the
scheduler directly as the server account, correlate owner, job name,
submission record, time, and script digest, then reconcile the durable MCP
record before another control operation.

## TS Tools and Authority

The TS-specific MCP tools are:

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

`ts-cluster-job/1` binds the submission, intent, node, backend, complete input
manifest, expected artifacts, scheduler resources, and execution environment.
Credential-like variables and `TS_CLUSTER_MCP_*` are rejected from scheduler
job environments.

The server stores the request before `qsub`. An identical submitted request is
replayed without another scheduler call. Reusing a `submission_id` with changed
content is rejected. A scheduler ID is persisted immediately after successful
`qsub`. A later persistence failure retains that known ID; an unknown outcome
becomes `ambiguous` and forbids automatic resubmission.

Cancellation first reserves the submission as `cancelling`. An unknown `qdel`
outcome becomes `cancellation_ambiguous` and automatic replay is refused.

Program and scheduler records are operational facts. Downloaded artifacts must
be verified locally, parsed deterministically, and registered through a later
`ts_workspace` decision before they become evidence. The calculation intent
selects `transport=mcp` but never contains the endpoint, bearer token, or other
credentials.

`ts_subagent_compute` exposes submission and cancellation through a
narrow host wrapper. It binds the intent, performs a read-only MCP connection
preflight, and creates a fresh child with exactly one request-scoped tool. The
Root Agent can invoke this path directly in interactive or headless Pi; the MCP
principal scopes, server policy, intent digest, target binding, and durable
control guards remain enforced.

## Register Gaussian For TS Jobs

Installing Gaussian on the cluster is not sufficient. The MCP server must have
a same-name `software.gaussian` profile so that `backend=gaussian` can bind a
server-owned activation script and queue policy before `qsub` is reachable:

```toml
[software.gaussian]
description = "Gaussian 16"
command = ["/home/agent/soft/gaussian/bin/gaussian16-run"]
activation_script = "/home/agent/soft/gaussian/activate_gaussian16.sh"
default_queue = "batch"
allowed_queues = ["batch", "fat", "fata"]
requires_gpu = false

[software.gaussian.environment]
GAUSSIAN16_DEFER_SCRATCH = "1"
```

The profile name must be exactly `gaussian`. The server validates profile
presence, activation-script existence, queue membership, and GPU requirements
before reserving a TS submission. Profile environment values override matching
intent environment values. The server then sources the activation script in
the PBS wrapper. The manifest-bound Gaussian runner creates a private random
scratch directory, exports `GAUSS_SCRDIR`, refuses to overwrite the declared
output, and cleans scratch on exit.

After restarting the service, use read-only checks only:

```text
/ts-mcp status
/ts-mcp cluster
```

The capability result must contain a `gaussian` profile with
`activation_script_exists=true` and the expected queue allowlist. The compute
operator repeats this check before creating a submit child.
Do not use a real Gaussian submission as a registration probe.
