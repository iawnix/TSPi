# Remote Execution Contract

`ts_remote` is the only remote-compute subsystem. It connects to one
installation-owned OpenSSH profile and controls Torque through bounded
`qsub`, `qstat`, `qdel`, and `pbsnodes` commands. There is no alternate remote
transport, nested compute-host login, HTTP service, tunnel manager, or
compatibility adapter.

Use `compute_operator.md` for complete Root `prepare`, `submit`, `inspect`,
`collect`, `cancel`, and `parse` calls. The fragments below define remote policy
only and are not complete `ts_subagent_compute` arguments.

The ownership boundary is:

```text
typed compute action
  -> ts_compute
  -> ts_remote
  -> OpenSSH/SCP
  -> Torque
```

`ts_compute` owns calculation intent and local attempt state. `ts_remote` owns
remote path construction, transfer verification, scheduler control, and
diagnostics. Backend adapters own program commands and parsing. None of these
layers may decide a mechanism, register evidence, or accept a transition state.

## Request Shape

The Agent may choose only the execution kind, configured profile name, and
bounded scheduler resources:

```json
{
  "kind": "remote",
  "profile": "cluster_1w",
  "resources": {
    "queue": "batch",
    "nodes": 1,
    "ncpus": 8,
    "memory": "16gb",
    "walltime": "04:00:00",
    "ngpus": 0,
    "mpiprocs": null,
    "ompthreads": 8
  }
}
```

The request cannot supply SSH hosts, scheduler commands, remote roots, program
commands, activation scripts, arbitrary environment variables, or destination
paths. Old requests with a transport selector or host/path fields fail schema
validation and are not converted.

## Installation Configuration

Set `TS_REMOTE_CONFIG` to an absolute, regular TOML file. `TSPi` uses
`<installation>/.pi/remote.toml` when present. Start from
`ts_remote/config.example.toml`:

```toml
default_profile = "cluster_1w"

[profiles.cluster_1w]
ssh_host = "cluster-login"
ssh_config = "/absolute/path/to/ssh_config"
scheduler = "torque"
remote_root = "/data2/agent/ts-remote-workspaces"
allowed_queues = ["batch"]
max_nodes = 1

[profiles.cluster_1w.software.gaussian]
command = ["/opt/gaussian/g16/g16"]
activation_script = "/opt/gaussian/g16/activate.sh"
# Optional; otherwise the execution node uses TMPDIR or /tmp.
scratch_root = "/local/scratch"
allowed_queues = ["batch"]
requires_gpu = false
```

SSH authentication stays in OpenSSH configuration and the user's agent or key
files. Secrets are not calculation-intent data. Software profiles are the only
source of executable paths, activation scripts, scratch roots, allowed queues,
GPU policy, and server-owned environment values. A configured `scratch_root`
must be an absolute non-root POSIX path. Gaussian otherwise uses the execution
node's `TMPDIR`, falling back to `/tmp`; a calculation request cannot override
this policy.

The Torque adapter creates one private per-job scratch directory. Gaussian
activation and program execution share that directory, and an `EXIT` trap
removes it on success or failure. `program_status.json` identifies failures in
the `scratch_setup`, `activation`, or `program` phase before scheduler history
is consulted.

## Workspace Isolation

Every initialized research workspace owns a stable non-scientific identity in
`.agents/workspace-identity.json`. The kernel derives the remote directory:

```text
<remote_root>/workspaces/<workspace_id>/runs/<node_id>/<intent_id>
```

The prepared execution policy binds the profile, workspace ID, complete remote
directory, and resource request. Later operations revalidate that binding.
Two independently initialized workspaces therefore cannot collide even when
their node and intent IDs match.

## Lifecycle

Prepare writes the immutable intent and `prepared.json`. It performs no remote
action.

Submit verifies input bindings, uploads the generated Torque script and all
declared inputs, and verifies each remote SHA-256. It then invokes one remote
submission script that acquires an atomic lock and persists:

```text
.ts-remote/submission.env
.ts-remote/qsub.stdout
.ts-remote/qsub.stderr
```

The submission record binds the submission ID and script digest. A successful
record also binds the Torque job ID. If SSH disconnects after the submission
script starts, the client immediately reads this record. An accepted or
rejected record resolves the outcome; a missing or incomplete record remains
ambiguous and cannot be resubmitted automatically.

Inspect reads the program-owned `program_status.json` and queries `qstat -f`.
Scheduler state and program state remain separate. Torque `C` is terminal but
does not by itself mean the scientific program failed. When scheduler history
has expired, a complete program-status record remains authoritative and the
scheduler error is returned as diagnostic metadata.

Collect verifies the prepared manifest, downloads only declared artifact
basenames, and verifies remote and local SHA-256 values. It never calls
`qstat`, so collection remains possible after scheduler history expires.

Cancel uses only the job ID from the bound remote receipt. Its remote atomic
record binds submission ID and job ID. An interrupted cancellation is
ambiguous and must be reconciled before another cancellation attempt.

## Failure Classes

- Directory creation or upload failure before the submission script starts:
  `remote_staging_failed`; retry is safe after fixing the cause.
- Durable nonzero `qsub` result: `scheduler_submission_rejected`; no job was
  accepted, but the immutable failed intent is not replayed. Correct the cause
  in a new intent.
- Submission script started but no authoritative record can be read:
  `submission_ambiguous`; do not retry submission.
- Program status says failed or Torque supplies a nonzero terminal exit:
  `remote_program_failed`.
- Scheduler history unavailable without a program record:
  `scheduler_history_unavailable`; state remains unknown.
- Cancellation started without a bound final record:
  `cancellation_ambiguous`; do not retry cancellation.

Control guards, raw results, reconciliations, and `remote_receipt.json` are
append-only operational facts. They are not scientific evidence.

## Diagnostics

Use `ts_remote_inspect` or:

```text
/ts-remote status
/ts-remote doctor
/ts-remote queues
/ts-remote nodes
```

These diagnostics are read-only. `status` checks OpenSSH connectivity;
`doctor` checks SSH, scheduler commands, storage, and registered software;
the remaining modes show bounded scheduler views. `./TSPi --check-remote`
runs the strict status check without creating a research workspace. Ordinary
TSPi startup does not probe the cluster and local research remains available
when the remote system is offline.
