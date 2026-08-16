# Installation And Operations

This guide installs one validated `@iawnix/ts-agent` release into a dedicated
TSPi root. It also covers workspace startup, configuration, upgrade, rollback,
and common recovery paths.

## Prerequisites

| Requirement | Purpose |
| --- | --- |
| Linux with OpenSSH client tools | TSPi host and optional remote execution |
| Node.js `>=22.19.0` | Pi and TypeScript extension loading |
| Pi Agent `>=0.81.1 <1.0.0` | Root Agent host and TUI |
| Python 3.11 or newer | release installer and runtime bootstrap |
| Conda or Mamba | isolated scientific Python environment |
| npm | release build and maintainer validation only |

Configure a working Pi model and authentication before starting TSPi. TSPi
reuses Pi's model registry and credentials; it does not store an API key in the
release or research workspace.

Optional dependencies are:

- a configured OpenSSH host and Torque installation for remote calculation;
- Gaussian, xTB, or other software profiles on the remote execution system;
- `xyzrender`, installed by `--with-render`, for visualization;
- a configured ClawEmail installation for email notifications;
- the separate TS Phone Broker and app for `--phone` mode.

## Installation Layout

Choose one physical, non-symlink installation root:

```text
<installation>/
  TSPi
  .pi/
    packages/ts-agent/
      current -> releases/<release-id>
      releases/<release-id>/
      install-state.json
    remote.toml                 optional
    notifications.toml          optional, mode 0600
    runtime-cache/
  .agents/
    runtime/transition-state-workflow/env.json
    envs/transition-state-workflow/<spec-hash>/
  workspaces/
    <workspace-name>/
```

Releases are immutable and shared. Workspaces keep separate Pi sessions,
canonical state, calculation controls, reports, and Root locks.

## Build A Release

Run this section in a clean authored Git checkout. End users receiving a
prebuilt archive and manifest can skip it.

```bash
python3 scripts/check_package.py
python3 scripts/build_release.py --output-dir dist --json
```

The build fails on a dirty checkout unless `--allow-dirty` is supplied. That
option is for local validation only and must not be used for a distributed
release. The output contains:

```text
dist/ts-agent-<version>-sha256-<digest>.tgz
dist/ts-agent-release.json
```

Keep both files together. The manifest binds the archive name, size, SHA-256,
package identity, source commit, and dirty state.

## Install Or Select A Release

Use the installer from the matching authored checkout:

```bash
python3 scripts/install_release.py \
  --manifest dist/ts-agent-release.json \
  --install-root /path/to/TSPi-installation \
  --json
```

The installer rejects symlinked roots, unsafe archive members, unexpected
development files, identity mismatches, size or digest mismatches, and writable
release contents. It extracts into a private staging directory, finalizes
read-only permissions, atomically switches `current`, and installs the top-level
`TSPi` symlink. Reinstalling identical content is idempotent.

The installer does not run Pi, install model credentials, create a research
workspace, contact a cluster, or create the Python environment.

Each installed release includes `README.md`, the three top-level guides under
`docs/`, and versioned ADRs under `docs/adr/`. They describe that exact packaged
version and remain readable under the selected `current` release; do not edit
them in place.

## Install The Python Runtime

Install one environment owned by the TSPi installation so all workspaces reuse
the same dependency set:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/TSPi-installation/.pi/packages/ts-agent/current

python3 "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --runtime-home /path/to/TSPi-installation/.agents/runtime/transition-state-workflow \
  --env-root /path/to/TSPi-installation/.agents/envs/transition-state-workflow \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

RDKit and its compatible NumPy range are core dependencies; `xyzrender` remains
optional. Omit `--with-render` when visualization is not required. Use
`--dry-run` to inspect the selected prefix and command. Use `--force` only when
the existing hash-addressed environment must be refreshed.

Before writing runtime manifest v2, the installer imports NumPy and RDKit,
parses a SMILES, performs fixed-seed ETKDG embedding, and completes a UFF
optimization. The manifest records versions, module origins, capabilities,
selected interpreter, and environment-spec digest outside the immutable
release. A failed probe produces no trusted manifest.

TSPi fails closed when that manifest is missing or stale. After selecting it,
TSPi places the managed environment first on `PATH`, exports
`TS_AGENT_PYTHON`, disables user site packages, and clears `PYTHONHOME` for the
entire Pi process tree. `TS_WORKSPACE_ROOT` still identifies only the selected
research workspace.

## Select The Pi Executable

The launcher uses `PI_BIN` when set. Otherwise it uses its configured default
path. Set an explicit executable for portable installations:

```bash
export PI_BIN=/absolute/path/to/pi
/path/to/TSPi-installation/TSPi --workspace smoke
```

Verify the selected Pi version is inside the package's supported range. Pi's
extension loader supplies its matching TypeBox runtime; the immutable TS release
does not contain `node_modules`.

## Configure Remote Execution

Remote execution is optional. Copy the packaged example into installation
state, then edit only installation-owned values:

```bash
mkdir -p /path/to/TSPi-installation/.pi
cp "$TS_AGENT_SKILL_ROOT/ts_remote/config.example.toml" \
  /path/to/TSPi-installation/.pi/remote.toml
chmod 600 /path/to/TSPi-installation/.pi/remote.toml
```

The profile owns:

- SSH host alias and SSH config path;
- Torque `qsub`, `qstat`, `qdel`, and `pbsnodes` command names;
- remote workspace root, allowed queues, and resource ceiling;
- software command, activation script, scratch policy, queue restrictions, and
  server-side environment.

Keep SSH keys and authentication in OpenSSH configuration, not in
`remote.toml`. A calculation request cannot override the host, remote root,
scheduler commands, activation scripts, or arbitrary environment values.

Check only SSH reachability:

```bash
cd /path/to/TSPi-installation
./TSPi --check-remote
```

Inside TSPi, `/ts-remote status` checks SSH, `doctor` checks SSH, scheduler,
remote storage, and registered software, while `queues` and `nodes` return their
bounded scheduler views. These commands are read-only. Ordinary startup does
not run any remote probe.

## Configure Notifications

Notifications are optional and fixed-target. Create exactly this installation
configuration and make it private:

```toml
[notifications.email]
enabled = true
recipient = "researcher@example.org"
clawemail_root = "/absolute/path/to/clawemail"
```

```bash
chmod 600 /path/to/TSPi-installation/.pi/notifications.toml
```

The configured ClawEmail root must contain its valid Skill, executable manager,
and private authentication state. The Root Agent may choose a supported research
event, subject, bounded summary, and existing report attachments, but it cannot
change the recipient or credentials. Set `enabled=false` to disable delivery.

The installation configuration is persistent authorization for that one target.
There is no per-message activation token. A mismatch between the user's
requested address and the configured target must be reported without sending.
Ambiguous provider effects are never retried automatically.

## Start And Resume Workspaces

Run from the installation root:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-b
```

The workspace name must contain 1 to 80 letters, digits, dots, underscores, or
hyphens and begin with a letter or digit. The launcher creates the directory;
the user does not create it manually.

To resume the latest Pi conversation for the same workspace:

```bash
./TSPi --workspace reaction-a --continue
```

Other Pi arguments may follow the workspace selection. `--phone` accepts no
additional Pi arguments and always uses `--continue`:

```bash
./TSPi --workspace reaction-a --phone
```

One process owns one workspace through a nonblocking lock. Starting a second
Root Agent for the same workspace fails immediately; another workspace can run
at the same time.

## Workspace Bootstrap

At startup:

- a fresh directory is initialized once while unrelated input files remain;
- a complete v4 workspace is validated without canonical rewrites;
- partial or invalid v4 state fails closed;
- legacy canonical markers fail closed.

Protocol v4 intentionally has no migration command, legacy reader, or field
alias. Continue a legacy workspace with the matching old release, or create a
new workspace name and explicitly re-establish only scientifically verified
inputs and Claims. Do not copy legacy canonical JSON into a v4 workspace.

## Upgrade

1. Validate and build a clean new release.
2. Preserve its archive and manifest.
3. Run `install_release.py` against the same installation root.
4. Run the newly selected release's `install_env.py`; a changed environment
   spec selects a new hash-addressed prefix.
5. Stop and restart each TSPi process when ready.

The `current` pointer switch is atomic. A process already running continues to
use the release and Python environment it started with. Upgrade does not rewrite
research workspaces or terminate active calculations.

## Rollback

The supported rollback path is to preserve a previous validated archive and
manifest and install it again:

```bash
python3 scripts/install_release.py \
  --manifest /path/to/previous/ts-agent-release.json \
  --archive /path/to/previous/ts-agent-<release-id>.tgz \
  --install-root /path/to/TSPi-installation \
  --json
```

Then run that selected release's `install_env.py` and restart TSPi. Existing
release directories are retained for inspection, but retention alone is not a
substitute for preserving the validated manifest and archive. Do not edit an
installed release or manually replace files under `current`.

Rollback changes package/runtime code only. It does not downgrade a v4
workspace or reverse already committed scientific Decisions. A v4 workspace
cannot be opened by a release that does not implement protocol v4.

## Operational Recovery

| Symptom | Meaning and action |
| --- | --- |
| `no installed TS Agent release` | Install a validated archive before startup. |
| runtime manifest or interpreter unavailable | Run the selected release's `install_env.py`. |
| managed runtime capability probe fails | Do not fall back to system Python. Recreate the hash-addressed environment and inspect the recorded NumPy/RDKit import error. |
| `another Root Agent already owns workspace` | Use another workspace or stop the existing process; do not delete the lock to bypass a live owner. |
| partial or invalid v4 workspace | Preserve the directory, inspect validation findings, and recover through an explicitly designed repair; startup will not guess. |
| legacy canonical state rejected | Use its matching release or start a separate fresh v4 workspace; this release has no migration path. |
| remote `status` fails | SSH readiness is unavailable; local research remains usable. |
| remote `doctor` fails | Inspect scheduler paths, remote root permissions, and each software profile. |
| `submission_ambiguous` or `cancellation_ambiguous` | Reconcile durable control records; do not replay the action. |
| notification config permission error | Set mode `0600` and verify the file is a regular non-symlink path. |
| no API key for selected model | Repair Pi's model/auth configuration; TS workspaces do not own provider keys. |
| Review run remains pending after a crash | Inspect its journal and independent calculation controls; no automatic stale-run resolver exists. |

## Installation Verification

After installation, verify without submitting a job:

```bash
readlink -f /path/to/TSPi-installation/.pi/packages/ts-agent/current
/path/to/TSPi-installation/TSPi --help
/path/to/TSPi-installation/TSPi --workspace smoke --continue
```

Use `--check-remote` only when a remote profile is configured and a strict SSH
probe is intended. Scientific validation and real program submission require
separate, explicit tests.
