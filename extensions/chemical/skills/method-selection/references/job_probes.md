# Remote Execution Contract

`job_start` owns the calculation lifecycle for both local and remote targets.
The remote adapter is the installation-bound OpenSSH/SCP and Torque transport;
it is not a second public calculation lifecycle. Use `job_probe` with the selected `platform` for a bounded availability check.

## Installation-Owned Policy

`job.toml` is the recommended shared policy file. Each environment declares a
`kind` and a `backends` table; `kind = "remote"` environments additionally own SSH
host/config, remote root, scheduler commands, queues, resource ceilings,
activation, scratch policy, and process environment. Local and remote environments
are defined in this one file; there is no separate remote registry. A calculation
request selects a named environment and resources within its configured limits.

This file is the single local/remote environment authority. Do not add a
second `.pi/remote.toml` registry or infer a remote environment from a host
directory. Pass the configured environment name as `platform` in `job_start`. An environment's optional software metadata
describes readiness; it is not a workflow registry or a launch gate beyond the
probe and transport checks.

`job_probe` checks platform availability, not scientific readiness. Inspect the
selected backend's command, activation script and Python binding. Use the relevant
program's bounded help/version check or Skill-specific doctor when required.
For CF22D, [doctor.py](../../cf22d/scripts/doctor.py) checks the configured
PySCF environment and method construction. It does not establish readiness for
other programs. There is no bundled NEB readiness probe or workflow registry.
Do not install scientific dependencies into a research workspace.

## Isolation

Remote directories are derived from workspace identity, ResearchNode, and
intent. The upload manifest binds regular files, sizes, SHA-256, command, environment,
resources, expected artifacts, and submission ID. Remote files provide the
execution copy; collection downloads declared outputs into the local workspace.

## Control Lifecycle

Submit persists pre-effect staging state before calling Torque. Once the
scheduler request begins, transport failure may be ambiguous. Preserve any
known job ID and durable submission record even if later queue/history lookup
fails.

Cancel similarly distinguishes known no-effect, known cancellation, and
ambiguous effect. When a job disappears from the queue, inspect its receipt
and declared outputs to establish what happened.

Inspect may combine durable receipt, scheduler state, program status, and a
bounded declared artifact tail. Collection follows the immutable artifact
manifest and works even when scheduler history is unavailable.

## Verify Results

- Reconcile an unknown submit or cancel result before another control action.
- Resolve remote paths and commands from the configured environment and intent.
- Check the selected platform and scientific command separately; SSH alone is insufficient.
- Check program termination and required outputs after scheduler completion.
- Collect outputs, verify them locally, and parse them before recording Findings.
