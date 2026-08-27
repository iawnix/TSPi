# Installation And Operations

This guide builds and installs one validated TSPi Package containing the Agent,
embedded Web explorer, TS Phone server, and signed Android artifact. It also
covers workspace startup, configuration, upgrade, rollback, and common recovery
paths.

## Prerequisites

| Requirement | Purpose |
| --- | --- |
| Linux with OpenSSH client tools | TSPi host and optional remote execution |
| Node.js `>=22.19.0` | Pi and TypeScript extension loading |
| Pi Agent `>=0.81.1 <1.0.0` | Root Agent host and TUI |
| Python 3.11 or newer | release installer and runtime bootstrap |
| Conda or Mamba | isolated scientific Python environment |
| npm | component release builds and maintainer validation only |

Configure a working Pi model and authentication before starting TSPi. TSPi
reuses Pi's model registry and credentials; it does not store an API key in the
release or research workspace.

Optional dependencies are:

- a configured OpenSSH host and Torque installation for remote calculation;
- Gaussian, xTB, or other software profiles on the remote execution system;
- `xyzrender`, installed by `--with-render`, for visualization;
- a configured ClawEmail installation for email notifications;
- TS Phone activation and an Android device when `--phone` is used. The broker
  and signed arm64 APK are bundled, but activation and device installation are
  explicit operations.

## Installation Layout

Choose one physical, non-symlink installation root:

```text
<installation>/
  TSPi
  TSWeb
  TSPhoneCtl
  TSPhoneServer
  .pi/
    packages/tspi/
      current -> releases/<suite-release-id>
      releases/<suite-release-id>/
        agent/
          python/ts_agent/           auditable Python source
          python-dist/*.whl          manifest-bound runtime artifact
        phone/
          services/server/dist/      TS Phone server
          artifacts/*.apk            signed Android artifact
        components/                  verified nested release archives
        components.json
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

The four top-level entrypoints resolve through the same suite `current` pointer.
Releases are immutable and shared. Workspaces keep separate Pi sessions,
canonical state, calculation controls, reports, and Root locks. Phone tokens,
service configuration, model credentials, and other runtime state remain
outside the release.

## Build A Release

Run this section with clean TS Phone and TSPi source checkouts. End users
receiving a prebuilt Package archive and manifest can skip it.

```bash
cd /path/to/ts-phone
npm ci
python3 deploy/build-component-release.py \
  --output-dir dist/component \
  --json

cd /path/to/TSPi
python3 scripts/check_package.py
python3 scripts/build_package.py \
  --phone-manifest /path/to/ts-phone/dist/component/ts-phone-component-release.json \
  --output-dir dist/package \
  --json
```

The Phone builder runs server typecheck, tests, and build, verifies the arm64
APK Signature Scheme 2 record, and writes `ts-phone-component-release/1`. The suite builder
internally builds the Agent component and wheel, verifies both component
manifests and archives, and writes `tspi-package-release/1`. Each build fails on
a dirty source unless `--allow-dirty` is supplied. That option is only for local
validation and must not be used for a distributed release.

The final output contains:

```text
dist/package/tspi-package-<version>-sha256-<digest>.tgz
dist/package/tspi-package-release.json
```

Keep both files together. The suite manifest binds the exact Agent and Phone
release IDs, nested archive paths, sizes and SHA-256 values, Agent wheel,
protocol set, Phone server entry, signed APK, component source commits, and the
outer archive identity. `build_release.py` and `install_release.py` remain
internal Agent-component tools; they do not produce or install a complete TSPi
deployment.

## Install Or Select A Release

Use the installer from the matching authored checkout:

```bash
python3 scripts/install_package.py \
  --manifest dist/package/tspi-package-release.json \
  --install-root /path/to/TSPi-installation \
  --json
```

The installer rejects symlinked roots, unsafe members in every archive,
unexpected development files, component/protocol mismatches, size or digest
mismatches, and writable release contents. It extracts into a private staging
directory, validates the expanded Agent, Web, Phone server, and APK, finalizes
read-only permissions, atomically switches one suite `current`, and installs
the top-level `TSPi`, `TSWeb`, `TSPhoneCtl`, and `TSPhoneServer` symlinks.
Reinstalling identical content is idempotent and revalidates retained component
archives and runtime entrypoints.

The installer does not run Pi, start or restart TS Phone, install the APK onto a
device, install model credentials, create a research workspace, contact a
cluster, or create the Python environment.

Each installed release includes `README.md`, the three top-level guides under
`docs/`, and versioned ADRs under `docs/adr/`. They describe that exact packaged
version and remain readable under the selected `current` release; do not edit
them in place.

## Install The Python Runtime

Install one environment owned by the TSPi installation so all workspaces reuse
the same dependency set:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/TSPi-installation/.pi/packages/tspi/current/agent

python3 "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --runtime-home /path/to/TSPi-installation/.agents/runtime/transition-state-workflow \
  --env-root /path/to/TSPi-installation/.agents/envs/transition-state-workflow \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

RDKit, Pillow, and their compatible NumPy range are core dependencies;
`xyzrender` remains optional. Pillow provides deterministic panel composition
but does not replace `xyzrender` as the molecular renderer. Omit `--with-render`
when visualization is not required. Use
`--dry-run` to inspect the selected prefix and command. Use `--force` only when
the existing hash-addressed environment must be refreshed.

The release already contains `python-dist/ts_agent_kernel-*.whl` plus its
identity, size, SHA-256, and payload digest in `ts-agent-release/2` metadata.
Before writing the runtime manifest, the installer revalidates that wheel and
installs it without resolving duplicate pip dependencies. It never invokes a
build backend against the read-only release tree. It then imports NumPy and
RDKit, parses a SMILES, performs fixed-seed ETKDG embedding, and completes a UFF
optimization. The manifest records the wheel provenance, installed
distribution version and payload digest, source payload digest, module origins,
capabilities, selected interpreter, and environment-spec digest outside the
immutable release. A failed install, digest comparison, or scientific probe
produces no trusted manifest.

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
cp "$TS_AGENT_SKILL_ROOT/python/ts_agent/remote/config.example.toml" \
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
Every attachment must be an unchanged member of a generated report package
manifest. To attach a Render result, pass its logical artifact ID to
`ts_report.assetArtifactIds`, then pass the returned `reports/.../assets/...`
reference to `ts_notify_user`; do not attach `nodes/...` paths directly.

The installation configuration is persistent authorization for that one target.
There is no per-message activation token. A mismatch between the user's
requested address and the configured target must be reported without sending.
Ambiguous provider effects are never retried automatically.

## Configure TS Phone

Phone mode is optional. The selected Package includes the compatible broker,
control CLI, protocol schemas, and signed arm64 APK. It does not own the live
service or its secrets. Copy the component's example environment into private
installation state and edit its workspace, state, and socket paths for the
installation:

```bash
mkdir -p /path/to/TSPi-installation/.pi/ts-phone
cp /path/to/TSPi-installation/.pi/packages/tspi/current/phone/deploy/server.env.example \
  /path/to/TSPi-installation/.pi/ts-phone/server.env
chmod 600 /path/to/TSPi-installation/.pi/ts-phone/server.env
```

An operator may run `/path/to/TSPi-installation/TSPhoneServer` under a service
manager or in a terminal after loading that environment. Service activation,
restart, FRP, HTTPS, and token handling remain explicit operational actions;
the Package installer never performs them. `TSPhoneCtl` targets the configured
state directory. The Android artifact is under the path recorded by
`components.phone.mobile_artifact.path` in the selected Package manifest and
must be installed on the device separately.

The `deploy/install-local.sh` and bundled systemd unit in the TS Phone source
repository are standalone component-development tools. Do not combine their
`/home/iaw/soft/ts-phone/current` selection with a suite-managed production
installation.

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
- a complete workspace is validated without canonical rewrites;
- partial or invalid state fails closed;
- unsupported canonical markers fail closed.

Startup never rewrites an existing workspace or guesses how unsupported state
should map into the active contract. Create a distinct workspace when the
existing layout is unsupported.

## Run The Research Explorer

`ts_web` is an optional read-only process. Keep its registry outside all source
workspaces and register one or more studies while starting the server:

```bash
/path/to/TSPi-installation/TSWeb serve \
  --state-dir /path/to/TSPi-installation/.pi/ts-web \
  --source-root /path/to/TSPi-installation/workspaces/reaction-a \
  --label "Reaction A" \
  --source-root /path/to/TSPi-installation/workspaces/reaction-b \
  --label "Reaction B" \
  --host 127.0.0.1 \
  --port 8766
```

The registry persists, so later starts may omit `--source-root`. When the state
directory is `<installation>/.pi/ts-web`, the server automatically treats
`<installation>/workspaces` as a managed discovery root. Startup and each
browser catalog refresh register direct children whose `workspace.json`
declares the supported workspace contract, and remove managed rows whose directory or identity file
has disappeared. A missing or unreadable discovery root is not pruned, and
manual registrations outside it remain untouched. Pass `--workspace-root`
repeatedly to override the inferred root. Use `register`, `list`, or `remove`
for external or specially labeled workspaces. Open `http://127.0.0.1:8766/` in
a browser.

The visible browser polls a revision-aware snapshot route every five seconds.
It pauses while hidden, never overlaps a manual refresh, and preserves the
current view, scroll position, and open inspector when data changes. An
unchanged response contains no View or Graph. If a check fails, the browser
keeps the last valid snapshot and marks its live status as stale.

Release watching is enabled by default. It works only when the process is
invoked through the stable `<installation>/TSWeb` path. After
`current` selects another immutable release, the watcher waits until that
release's managed Python runtime is ready, gracefully closes the HTTP server,
and executes the same stable command. Pass `--no-watch-release` to disable this
behavior for diagnosis. The restart has a short connection gap; it is not
development source reload or zero-downtime socket transfer.

The explorer validates current state on read and exposes no mutation endpoint.
Its default route is the ResearchNode dependency tree, with ResearchPhase used
only for navigation and focus. The Claim graph is an advanced view; the Node DAG
is not duplicated there. File preview is bounded to current ResearchNode files;
only UTF-8 text within the configured byte limit is presented as previewable.
The server does not implement user authentication. Bind `127.0.0.1` by default; bind
`0.0.0.0` only for a trusted, firewalled LAN and assume every reachable client
can inspect the registered research data.

## Upgrade

1. Validate and build clean Phone and Agent components into a new Package.
2. Preserve its archive and manifest.
3. Run `install_package.py` against the same installation root.
4. Run the newly selected release's `install_env.py`; a changed environment
   spec selects a new hash-addressed prefix, while an unchanged prefix still
   receives and verifies the release-bound wheel.
5. Stop and restart each TSPi Root Agent process when ready. Restart TS Phone
   only in an authorized maintenance window. A `TSWeb` process
   started through the stable `current` entrypoint restarts itself after the new
   managed runtime is ready.

The `current` pointer switch is atomic. A process already running continues to
use the release and Python environment it started with unless it implements the
explicit Web release watcher above. Upgrade does not rewrite research workspaces
or terminate active calculations.

During installation, obsolete `.pi/ts-email-delivery-policy.json` and
`.pi/ts-email-delivery-authorization.json` files are moved into a private
`.pi/archive/retired-notification-state/<timestamp>/` directory. They are kept
for audit only and are never read as authorization by this release.

## Rollback

The supported rollback path is to preserve a previous validated archive and
manifest and install it again:

```bash
python3 scripts/install_package.py \
  --manifest /path/to/previous/tspi-package-release.json \
  --archive /path/to/previous/tspi-package-<release-id>.tgz \
  --install-root /path/to/TSPi-installation \
  --json
```

Then run that selected release's `install_env.py` and restart TSPi. Existing
release directories are retained for inspection, but retention alone is not a
substitute for preserving the validated manifest and archive. Do not edit an
installed release or manually replace files under `current`.

Rollback changes package/runtime code only. It does not rewrite a workspace or
reverse already committed scientific Decisions. The selected release must
implement the workspace schemas it opens.

## Operational Recovery

| Symptom | Meaning and action |
| --- | --- |
| no selected TSPi Package release | Install a validated Package archive before startup. |
| runtime manifest or interpreter unavailable | Run the selected release's `install_env.py`. |
| managed runtime capability probe fails | Do not fall back to system Python. Recreate the hash-addressed environment and inspect the recorded NumPy/RDKit import error. |
| Python distribution payload mismatch | Rerun the selected release's `install_env.py`; do not edit the managed site-packages or immutable release in place. |
| `another Root Agent already owns workspace` | Use another workspace or stop the existing process; do not delete the lock to bypass a live owner. |
| partial or invalid workspace | Preserve the directory, inspect validation findings, and recover through an explicitly designed repair; startup will not guess. |
| unsupported workspace layout | Preserve the source directory and start a separate fresh workspace; startup never rewrites unsupported state. |
| remote `status` fails | SSH readiness is unavailable; local research remains usable. |
| remote `doctor` fails | Inspect scheduler paths, remote root permissions, and each software profile. |
| `submission_ambiguous` or `cancellation_ambiguous` | Reconcile durable control records; do not replay the action. |
| notification config permission error | Set mode `0600` and verify the file is a regular non-symlink path. |
| notification attachment rejected | Build a report package containing the logical image artifact, then attach only unchanged paths listed by that package manifest. |
| notification delivery state is `unknown` | Inspect the receipt and provider Sent folder; do not replay automatically. |
| no API key for selected model | Repair Pi's model/auth configuration; TS workspaces do not own provider keys. |
| Review run remains pending after a crash | Inspect its journal and independent calculation controls; no automatic stale-run resolver exists. |

## Installation Verification

After installation, verify without submitting a job:

```bash
readlink -f /path/to/TSPi-installation/.pi/packages/tspi/current
/path/to/TSPi-installation/TSPi --help
/path/to/TSPi-installation/TSWeb --help
/path/to/TSPi-installation/TSPhoneCtl --help
/path/to/TSPi-installation/TSPhoneServer --help
/path/to/TSPi-installation/TSPi --workspace smoke --continue
```

Use `--check-remote` only when a remote profile is configured and a strict SSH
probe is intended. Scientific validation and real program submission require
separate, explicit tests.
