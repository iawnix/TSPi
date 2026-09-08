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
| Android SDK build-tools with `apksigner` and `aapt` | independent APK verification during Package build and install |
| npm | component release builds and maintainer validation only |

Configure a working Pi model and authentication before starting TSPi. TSPi
reuses Pi's model registry and credentials; it does not store an API key in the
release or research workspace.

Optional dependencies are:

- a configured OpenSSH host and Torque installation for remote calculation;
- Gaussian, xTB, or other software profiles on the remote execution system;
- `xyzrender`, installed by `--with-render`, for visualization;
- a configured ClawEmail installation for email notifications;
- an Android device for the Phone UI. The Host and signed arm64 APK are bundled,
  but service activation and device installation are explicit operations.

The default terminal client requires the configured Host to be running. It
does not require an Android device. Native Pi remains available with
`--standalone`.
The installer prepares an empty private `workspaces/` root so Host can list
projects before the first Worker runs. It does not bootstrap scientific state
or activate services during installation.

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
          artifacts/*.attestation.json  source/build binding
        components/                  verified nested release archives
        components.json
      install-state.json
    remote.toml                 optional
    notifications.toml          optional, mode 0600
    runtime-cache/
  .agents/
    runtime/transition-state-workflow/env.json
    envs/transition-state-workflow/
      base/<spec-hash>/             shared scientific dependencies
      kernels/<payload-hash>/       exact release ts-agent-kernel
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
apps/mobile/tool/build_release_android.sh
python3 deploy/build-component-release.py \
  --output-dir dist/component \
  --json

cd /path/to/TSPi
export TSPI_ANDROID_BUILD_TOOLS=/path/to/android-sdk/build-tools/<version>
python3 scripts/build_package.py \
  --phone-manifest /path/to/ts-phone/dist/component/ts-phone-component-release.json \
  --output-dir dist/package \
  --json
```

The Phone build runs from a private source capture and embeds its source
snapshot into each signed Android artifact. The component builder runs server
typecheck, tests, and build from the same capture, verifies the arm64
APK Signature Scheme v2 record, pinned certificate, package metadata, build
attestation, and writes `ts-phone-component-release/2`. Android artifacts are
published as one content-addressed set behind `dist/android-current`. The suite
builder independently repeats the Phone checks, builds the Agent component and wheel
from one private Git-visible source capture,
and writes `tspi-package-release/2`. Each build fails on a dirty source unless
`--allow-dirty` is supplied. That option is only for local validation and must
not be used for a distributed release.

The complete Package contains the arm64 APK, not the store AAB. TS Phone checks
the AAB signature, sole pinned signer, source identity, and attestation, but a
pinned `bundletool` metadata check is still required before store upload. Its
Android build also records source provenance rather than content identities for
the Flutter, Android SDK, and JDK toolchain, so the current contract does not
claim bit-for-bit reproducibility across build hosts.

The final output contains:

```text
dist/package/tspi-package-<version>-sha256-<digest>.tgz
dist/package/tspi-package-release.json
```

Keep both files together. The suite manifest binds the exact Agent and Phone
release IDs, nested archive paths, sizes and SHA-256 values, Agent wheel,
protocol set, Phone server entry, signed APK, embedded source snapshot, mobile
build attestation, component source identities, and the outer archive identity.
`build_release.py` and `install_release.py` remain
internal Agent-component tools; they do not produce or install a complete TSPi
deployment.

## Install Or Select A Release

Use the installer from the matching authored checkout:

```bash
python3 scripts/install_package.py \
  --manifest dist/package/tspi-package-release.json \
  --install-root /path/to/TSPi-installation \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

Set `TSPI_ANDROID_BUILD_TOOLS` to the Android SDK build-tools directory that
contains `apksigner` and `aapt`. If it is unset, TSPi searches
`ANDROID_SDK_ROOT`, `ANDROID_HOME`, and then `PATH`. Verification fails closed
when the tools are unavailable. The installer rejects dirty-source components
by default; `--allow-dirty` is an explicit local-validation override.

The installer rejects symlinked roots, unsafe members in every archive,
unexpected development files, component/protocol mismatches, size or digest
mismatches, untrusted or misidentified APKs, and writable release contents. It
captures the outer archive once into private staging, validates and extracts
that same byte sequence, then validates the expanded Agent, Web, Phone server,
APK, embedded source identity, and attestation before finalizing read-only
permissions. Before activation it prepares the target
release runtime and runs the NumPy/RDKit capability probe. Only a healthy
runtime may publish its manifest and atomically switch the suite `current`.
On reinstall, every expanded Phone file and its executable class is compared
with the retained, digest-bound component archive. Activation failure restores
the prior manifest, pointer, install state, and
entrypoint links. Reinstalling identical content is idempotent and revalidates
retained component archives and runtime entrypoints.

The installer creates or reuses the managed Python runtime, but it does not run
Pi, start or restart TS Phone, install the APK onto a device, install model
credentials, create a research workspace, or contact a cluster.

Each installed release includes `README.md`, the three top-level guides under
`docs/`, and versioned ADRs under `docs/adr/`. They describe that exact packaged
version and remain readable under the selected `current` release; do not edit
them in place.

## Managed Python Runtime

Normal Package installation prepares this runtime before activation. The
standalone runtime command remains available for diagnosis or explicit repair:

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

The runtime has two layers. `base/<spec-hash>` is a shared Conda environment
containing RDKit, NumPy, SciPy, Pillow, pytest, and optional `xyzrender`.
`kernels/<payload-hash>` is a venv with system site packages enabled and only
the exact release wheel installed. An unchanged dependency spec therefore
reuses the heavy scientific base, while each distinct Python payload receives
its own small overlay. Omit `--with-render` when visualization is not required.
Use `--dry-run` to inspect both paths. Use `--force` only to refresh the selected
base and recreate the exact target overlay; unrelated overlays are retained.

The release already contains `python-dist/ts_agent_kernel-*.whl` plus its
identity, size, SHA-256, and payload digest in `ts-agent-release/2` metadata.
Before writing the runtime manifest, the installer revalidates that wheel and
installs it into the overlay without resolving duplicate pip dependencies. It
never invokes a build backend against the read-only release tree. It then
imports NumPy and RDKit from the base, imports `ts-agent-kernel` from the
overlay, parses a SMILES, performs fixed-seed ETKDG embedding, and completes a
UFF optimization. The manifest records the wheel provenance, installed
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

The launcher flag below is the command-line form of the same read-only
connectivity check exposed in Pi as `/ts-remote status`:

```bash
cd /path/to/TSPi-installation
./TSPi --check-remote
```

Use `/ts-remote doctor` for the full SSH, scheduler, storage, and registered
software chain; `queues` and `nodes` return bounded scheduler views. All four
diagnostics are read-only. Ordinary startup does not run a remote probe.

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
reference to `ts_notify`; do not attach `nodes/...` paths directly.

The installation configuration is persistent authorization for that one target.
There is no per-message activation token. A mismatch between the user's
requested address and the configured target must be reported without sending.
Ambiguous provider effects are never retried automatically.

## Configure TS Phone

Phone mode is optional. The selected Package includes the compatible broker,
control CLI, protocol schemas, and signed arm64 APK. It does not own the live
service or its secrets. Copy the component's example environment into private
installation state. Paths are inferred by the installed entrypoints; uncomment
only the overrides this installation needs:

```bash
mkdir -p /path/to/TSPi-installation/.pi/ts-phone
cp /path/to/TSPi-installation/.pi/packages/tspi/current/phone/deploy/server.env.example \
  /path/to/TSPi-installation/.pi/ts-phone/server.env
chmod 600 /path/to/TSPi-installation/.pi/ts-phone/server.env
```

The installed terminal client, Host, and control CLI read this owner-only file
as dotenv data, without executing it. Explicit environment variables take precedence. In a
unified installation these bindings default to the invoked installation root:

```dotenv
TS_PHONE_TSPI=/path/to/TSPi-installation/TSPi
TS_PHONE_WORKSPACES=/path/to/TSPi-installation/workspaces
```

`TS_PHONE_TSPI` must be an absolute executable path. Unified entrypoints reject
bindings to another installation; the standalone Phone development server still
requires an explicit launcher to activate sessions.
The app's project and conversation names, model/access preferences, and
active/archive/trash state live in owner-only
`TS_PHONE_STATE_DIR/management.json`; scientific state and conversation text
remain in their existing TSPi workspace and Pi JSONL owners.

An operator may run `/path/to/TSPi-installation/TSPhoneServer` under a service
manager or directly in a terminal; both load the same installation configuration.
The Package installer creates `.pi/ts-phone/ts-phone.service` only if absent,
using the configured paths and retaining the narrow sandbox. Existing templates
and live service registrations are not overwritten. Inspect an updated template
without starting anything with `TSPhoneServer --print-service`.
Service activation,
restart, FRP, HTTPS, and token handling remain explicit operational actions;
the Package installer never performs them. `TSPhoneCtl` targets the configured
state directory. The Android artifact is under the path recorded by
`components.phone.mobile_artifact.path` in the selected Package manifest and
must be installed on the device separately.

The `deploy/install-local.sh` and bundled systemd unit in the TS Phone source
repository are standalone component-development tools. Do not combine their
`/home/iaw/soft/ts-phone/current` selection with a suite-managed production
installation.

If the Host runs with `ProtectHome=read-only`, its service sandbox also applies
to child TSPi Workers. Add narrowly scoped `ReadWritePaths` for the configured
workspace root, `.pi/runtime-cache`, `.pi/session-host`, `.agents/runtime`, and `.agents/envs` under
the TSPi installation. Keep the rest of Home read-only. A notification provider
that refreshes credentials needs a separate drop-in for only its private state
directory.

Pi's selected agent directory must also be writable: credential and model-cache
reads acquire filesystem locks. The standard profile is `~/.pi/agent` for the
user running the Host. In a user service add `ReadWritePaths=-%h/.pi/agent`:
systemd expands `%h` to that user's Home, but does not expand shell `~` or
`$HOME` in this directive. A custom `PI_CODING_AGENT_DIR` needs an explicit
matching absolute path instead; the environment variable does not change the
service's filesystem allowlist. Preserve the same profile for TUI, Phone Workers
and subagents,
including OAuth write-back, rather than making per-workspace credential copies.
Do not disable `ProtectHome` or grant access to all of Home. Managed Workers
disable startup catalog/package downloads with `PI_OFFLINE=1`; this does not
disable model requests. Verify model readiness under the actual Host service
permissions: `/healthz` alone does not exercise Pi's storage or selected model.

## Start And Resume Workspaces

Run from the installation root:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-b
```

The terminal connects to the configured Host. An existing live Controller is
selected first; otherwise choose a conversation. Opening history starts no
Worker. An unknown workspace name prompts for project creation through Host;
the user does not create directories manually. Names contain 1 to 80 letters,
digits, dots, underscores, or hyphens, beginning with a letter or digit.
Without `--workspace`, the project selector is the first screen.

To resume the latest Pi conversation for the same workspace:

```bash
./TSPi --workspace reaction-a --continue
```

`--phone` aliases the shared terminal. Select an exact conversation or use
explicit native Pi mode when native commands are needed:

```bash
./TSPi --workspace reaction-a --phone
./TSPi --workspace reaction-a --phone --session-id <session-id>
./TSPi --standalone --workspace reaction-a
./TSPi --standalone --workspace reaction-a --phone --phone-access observer
```

The client reads `<installation>/.pi/ts-phone/server.env` as data, never as a
shell script; exported `TS_PHONE_HOST`, `TS_PHONE_PORT`, and `TS_PHONE_STATE_DIR`
override it. The default state directory is `${XDG_STATE_HOME:-~/.local/state}/ts-phone`.
It accepts only loopback HTTP and a user-owned 0600 `auth.token`. This is the
Host connection credential, not Pi's model authentication. Host unavailability
is reported without falling back to a second Pi process. See [Terminal](TERMINAL.md)
for client commands, limitations, and integration checks.

The phone app can instead create a managed project/conversation and ask the Host
to activate it. Host-only `--phone-worker`, `--lifecycle-preflight`, and
`--lifecycle-guard`, `--session-host-capabilities`, and `--session-writer-check`
syntax is not a supported manual interface. Worker mode
binds an exact session ID and access mode; preflight is a read-only, fail-closed
check. Guard mode excludes every session writer, including Observer, while the
Host deletes data. Guard files are under installation `.pi/session-host/guards/`;
allow this operational state path in the service sandbox, but never remove an
occupied lock file to force access.

The phone's Continue research action explicitly requests Controller and keeps
the original session ID and context; it does not require a visible terminal.
Read-only assistant is a separate menu action. A matching live runtime is
reused. Switching an idle Host-owned runtime requires confirmation; running,
queued, uncertain, or external CLI runtimes are not stopped. Activation alone
never submits the local draft. Model authentication is configured on the TSPi
host, separately from the phone connection token.

The first install enabling the guard activation record requires old TSPi writers
to exit after their turns finish, including Observer CLIs. Run the installer as
the installation owner, not inside the Host sandbox. It verifies unguarded writers
and holds affected workspace locks before publishing `session_guard_contract`
in the existing install-state record. A failed check does not select the new
release or mark the upgrade complete. Never create that record by hand.
Later same-contract updates do not repeat global process inspection. Normal
startup uses only the installation record and actual workspace/session locks;
unrelated Pi processes with private `/proc` state do not block it.
Downgrading to a suite without these guards requires stopping every affected
writer first. It restores that suite's limited behavior, not the new guarantees.

Native guarded TSPi supports a new conversation, `--continue`/`-c`, `--session-id`,
and an existing workspace-local `--session` file. Interactive `--resume`,
`--fork`, `--no-session`, session-directory overrides, and in-process new/fork/
resume are rejected; exit and reopen the desired session instead. Raw Pi
launches outside TSPi are not protected by this contract.

One Worker owns a workspace through a nonblocking lock. Multiple terminal and
Phone clients attach without acquiring locks. Terminal exit only detaches;
`/abort` stops generation without canceling remote calculations. A second
native Root Agent still fails immediately. An existing native Pi process
cannot be adopted by PID: exit it normally before Host restores its exact
conversation. Another workspace can run at the same time.

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
Its default Research Map groups each Phase into shared work and hypothesis
lanes, with recorded connectivity evidence derived only from structured
endpoint Observations. This evidence display is not a validation verdict. The
secondary Dependency DAG mode preserves the exact Node
topology for audit. Scientific Conclusions provides Table and Map modes over the
Claim graph. File preview is bounded to current ResearchNode files;
only UTF-8 text within the configured byte limit is presented as previewable.
The server does not implement user authentication. Bind `127.0.0.1` by default; bind
`0.0.0.0` only for a trusted, firewalled LAN and assume every reachable client
can inspect the registered research data.

## Upgrade

1. Validate and build clean Phone and Agent components into a new Package.
2. Preserve its archive and manifest.
3. Run `install_package.py` against the same installation root and Conda root;
   it prepares and probes the target runtime before selecting the release.
4. Stop and restart each TSPi Root Agent process when ready. Restart TS Phone
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
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

The installer reuses the previous payload overlay when it still passes its
probe, then selects the previous release. Existing release directories and
overlays are retained for inspection, but retention alone is not a substitute
for preserving the validated manifest and archive. Do not edit an installed
release or manually replace files under `current`.

Rollback changes package/runtime code only. It does not rewrite a workspace or
reverse already committed scientific Decisions. The selected release must
implement the workspace schemas it opens.

## Operational Recovery

| Symptom | Meaning and action |
| --- | --- |
| no selected TSPi Package release | Install a validated Package archive before startup. |
| runtime manifest or interpreter unavailable | Reinstall the selected Package, or run its `install_env.py` as an explicit repair. |
| managed runtime capability probe fails | Do not fall back to system Python. Refresh the shared base or recreate only the target overlay with `--force`, then inspect the NumPy/RDKit probe error. |
| Python distribution payload mismatch | Reinstall the Package or recreate its payload-addressed overlay; do not edit managed site-packages or immutable release files in place. |
| `another Root Agent already owns workspace` | Attach with the default terminal instead of `--standalone`. A native/external owner must exit normally before Host can restore its session; never delete a live owner's lock. |
| partial or invalid workspace | Preserve the directory, inspect validation findings, and recover through an explicitly designed repair; startup will not guess. |
| unsupported workspace layout | Preserve the source directory and start a separate fresh workspace; startup never rewrites unsupported state. |
| remote `status` fails | SSH readiness is unavailable; local research remains usable. |
| remote `doctor` fails | Inspect scheduler paths, remote root permissions, and each software profile. |
| `submission_ambiguous` or `cancellation_ambiguous` | Reconcile durable control records; do not replay the action. |
| notification config permission error | Set mode `0600` and verify the file is a regular non-symlink path. |
| notification attachment rejected | Build a report package containing the logical image artifact, then attach only unchanged paths listed by that package manifest. |
| notification delivery state is `unknown` | Inspect the receipt and provider Sent folder; do not replay automatically. |
| no API key for selected model | Repair Pi's model/auth configuration; TS workspaces do not own provider keys. |
| Phone session cannot activate | Verify `TS_PHONE_TSPI`, service sandbox write paths, Bridge socket/secret ownership, and the selected model's Pi authentication. |
| Phone project deletion is blocked | Finish or reconcile Workers, remote calculations, approvals, and unresolved remote effects. Do not bypass a failed lifecycle preflight. |
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

The remote check above is optional and only tests transport reachability;
scientific validation and real program submission require separate, explicit
tests.
