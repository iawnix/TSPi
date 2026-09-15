# Installation And Operations

Install TSPi from GitHub, choose Web and Phone extensions, and configure your
research environment. This guide also covers services, workspaces, upgrades,
rollback, uninstall, and recovery.

## Interactive Installer

Clone the private repository with an authorized SSH key, then run its thin
bootstrap for first-time setup:

```bash
git clone git@github.com:iawnix/TSPi.git
cd TSPi
./install.sh
```

The wizard asks for the installation directory, TSPi and TS Phone revisions,
optional TS Web and molecular rendering support, the Phone port, Conda location,
and systemd services. Selecting TS Phone fetches its GitHub source, installs npm
dependencies, builds the server, checks compatibility, and installs
`TSPhoneServer` and `TSPhoneCtl`. The server build uses Node.js and npm. Install
the Android client on the phone separately; Flutter and signing tools are needed
only when building Android artifacts.

Interactive install and uninstall screens use semantic colors when their output
stream is a TTY. Set the standard `NO_COLOR` environment variable to disable
ANSI colors. Machine-readable JSON on stdout never includes terminal styling.

Branches and tags resolve to full commit IDs recorded with each installation.
Use full SHAs for `--tspi-ref` and `--phone-ref` to repeat a particular version.
The non-interactive equivalent is:

```bash
./install.sh --non-interactive --yes \
  --install-root /path/to/TSPi-installation \
  --with-phone --with-web \
  --service-scope user --enable-services --start-services
```

`--with-phone` installs the Phone service; `--without-phone` skips this step.
Interactive setup offers Phone by default. Non-interactive setup installs it
when `--with-phone` is supplied. `--phone-repo` selects its GitHub repository,
`--phone-ref` defaults to `main`, and `--phone-port` sets the port for a new
configuration. Re-running the wizard keeps existing `server.env`, credentials,
and conversations. A failed Phone build leaves the selected Phone release
unchanged. Previous builds remain available under `.pi/ts-phone/releases/`.

The default service scope is the current user's systemd manager. Select the
system scope only when running as root. TSPi itself remains an interactive
launcher; the wizard creates services for TS Phone and optional TS Web.

## Uninstall

Run the `uninstall.sh` included in the installation directory:

```bash
/path/to/TSPi-installation/uninstall.sh
```

The repository-level `uninstall.sh` remains available only as a recovery entry
point when an installation's local copy has been removed.

By default it disables services belonging to the selected installation, removes
TSPi releases, installed Phone server builds, and managed runtime links, and keeps workspaces, Pi
sessions, Phone tokens, bridge secrets, and installation configuration. The
interactive wizard can separately purge workspaces, configuration, managed
runtime state, or the dedicated installation root. Destructive data choices
default to **No**. The final execution confirmation defaults to **Yes**, so
pressing Enter throughout performs a normal uninstall while preserving user
data. To remove all data and the installation root in a non-interactive run:

```bash
./uninstall.sh --non-interactive --yes \
  --install-root /path/to/TSPi-installation \
  --purge-workspaces --purge-config --purge-runtime --remove-root
```

Global Pi credentials under `~/.pi/agent` remain available for other Pi sessions.

## Prerequisites

| Requirement | Purpose |
| --- | --- |
| Git | Fetch TSPi and selected components from GitHub |
| Linux with OpenSSH client tools | TSPi host and optional remote execution |
| Node.js `>=22.19.0` | Pi and TypeScript extension loading |
| Pi Agent `0.85.1` | Validated Root Agent host, Harness, and TUI |
| Python 3.11 or newer | release installer and runtime bootstrap |
| Conda or Mamba | isolated scientific Python environment |
| npm | Phone server builds and component release tooling |

Configure a working Pi model and authentication before starting TSPi. TSPi
uses Pi's model registry and credentials from its configured agent directory.

Optional dependencies are:

- a configured OpenSSH host and Torque installation for remote calculation;
- Gaussian, xTB, or other software profiles on the remote execution system;
- `xyzrender`, installed by `--with-render`, for visualization;
- a configured ClawEmail installation for email notifications;
- an Android device and the TS Phone app for mobile access;
- Android SDK build-tools with `apksigner` and `aapt` when building or installing
  a Package that includes an Android APK.

The default terminal client connects to the configured Host. Start its service
before opening a shared session, or use `--standalone` to start native Pi.
The installer prepares `workspaces/` so the Host can list projects before the
first research session. The wizard enables and starts services when selected.

## Installation Layout

Choose one dedicated, physical installation root. The wizard, Package installer,
and Core release installer all require an absolute path; reject `/`, the current
user's home directory, and its parent; and reject control characters, double
quotes, backslashes, or a symbolic link anywhere in the path:

```text
<installation>/
  TSPi
  TSWeb                         optional Web component
  TSPhoneCtl                    optional Phone component
  TSPhoneServer                 optional Phone component
  .pi/
    packages/tspi/
      current -> releases/<suite-release-id>
      releases/<suite-release-id>/
        agent/
          packages/ts-agent-kernel/ts_agent/           auditable Python source
          python-dist/*.whl          manifest-bound runtime artifact
        web/                      present only when Web is selected
          bin/ts-web              independent Web entrypoint
          ts_web/                 provider client and HTTP server
          static/                 browser assets
        phone/                    present only when Phone is selected
          services/server/dist/      TS Phone server
          artifacts/*.apk            signed Android artifact
          artifacts/*.attestation.json  source/build binding
        components/                  verified nested release archives
        components.json
      install-state.json
    remote.toml                 optional
    notifications.toml          optional, mode 0600
    runtime-cache/
    ts-phone/
      server.env
      current -> releases/<phone-commit>
      releases/<phone-commit>/   server built by the installation wizard
        installation.json
        services/server/dist/
    ts-phone-state/              Phone credentials and conversation management
  .agents/
    runtime/tspi/env.json
    envs/tspi/
      base/<spec-hash>/             shared scientific dependencies
      kernels/<payload-hash>/       exact release ts-agent-kernel
  workspaces/
    <workspace-name>/
```

The selected top-level entrypoints resolve through the same suite `current`
pointer: `TSPi` is always present; `TSWeb` is present when Web is selected;
`TSPhoneCtl` and `TSPhoneServer` are present when Phone is selected. Releases
are immutable and shared. Workspaces keep separate Pi sessions,
canonical state, calculation controls, reports, and Root locks. Phone tokens,
service configuration, model credentials, and other runtime state remain
outside the release.

This is a TSPi application distribution layout, not a Pi package-manager
installation. The `pi` entries in `package.json` remain the authored extension-mode
surface, while the suite installer owns immutable application releases,
component selection, managed Python runtimes, and stable launchers.

## Build A Release

Run this section with a clean TSPi source checkout. Build the required Agent and
independent Web component without Phone as follows:

```bash
cd /path/to/TSPi
python3 scripts/build_package.py \
  --output-dir dist/package \
  --json
```

To include Phone, first build a clean TS Phone component and pass its manifest:

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
and writes `tspi-package-release/4`. The package manifest selects the optional
Phone and Web component set for each installation.
Each build fails on a dirty source unless
`--allow-dirty` is supplied. That option is only for local validation and must
not be used for a distributed release.

An APK-inclusive Package contains the Phone arm64 APK. TS Phone's Android
release process checks its signature, pinned signer, source identity, and build
attestation. Store AAB preparation and toolchain records are maintained in the
[Phone release instructions](https://github.com/iawnix/ts-phone/blob/main/docs/artifacts.md).

The final output contains:

```text
dist/package/tspi-package-<version>-sha256-<digest>.tgz
dist/package/tspi-package-release.json
```

Keep both files together. The suite manifest binds the exact Agent release and
the selected Web and Phone descriptors, nested archive paths, sizes and
SHA-256 values, Agent wheel, protocol sets, Phone server entry, signed APK,
embedded source snapshot, mobile build attestation, component source
identities, and the outer archive identity.

For production, use the source-first installer so the checkout, commit, and
tree digest are recorded before activation:

```bash
python3 scripts/install_from_github.py \
  --repo git@github.com:iawnix/TSPi.git --ref v0.17.0 \
  --install-root /srv/tspi --with-web --with-render
```

`--ref` accepts a branch, tag, or full commit SHA. For APK-inclusive Packages,
select TS Phone with `--phone-repo` and `--phone-ref`.
`build_release.py` and `install_release.py` support Agent-component development;
use the package tools above for a complete TSPi installation.

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
that same byte sequence, then validates the expanded Agent and each selected
optional component, including the Phone server, APK, embedded source identity,
and attestation when Phone is selected, before finalizing read-only permissions.
Before activation it prepares the target
release runtime and runs the NumPy/RDKit capability probe. Only a healthy
runtime may publish its manifest and atomically switch the suite `current`.
On reinstall, every expanded Phone file and its executable class is compared
with the retained, digest-bound component archive. Activation failure restores
the prior manifest, pointer, install state, and
entrypoint links. Reinstalling identical content is idempotent and revalidates
retained component archives and runtime entrypoints.

`install_package.py` prepares the package and managed Python runtime. Use the
installation wizard for service setup, then start a research session through
`TSPi`. Install the Android app on the device when using mobile access.

Each installed release includes both READMEs, guides under `docs/`, and ADRs
under `docs/adr/`. These documents describe the selected packaged version.

## Managed Python Runtime

Normal Package installation prepares this runtime before activation. The
standalone runtime command remains available for diagnosis or explicit repair:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/TSPi-installation/.pi/packages/tspi/current/agent

python3 "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --runtime-home /path/to/TSPi-installation/.agents/runtime/tspi \
  --env-root /path/to/TSPi-installation/.agents/envs/tspi \
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
then imports NumPy and RDKit from the base, imports `ts-agent-kernel` from the
overlay, parses a SMILES, performs fixed-seed ETKDG embedding, and completes a
UFF optimization. The manifest records the wheel provenance, installed
distribution version and payload digest, source payload digest, module origins,
capabilities, selected interpreter, and environment-spec digest outside the
immutable release. A failed install, digest comparison, or scientific probe
produces no trusted manifest.

If the manifest is missing or stale, repair the runtime with the installer.
After selecting it, TSPi places the managed environment first on `PATH`, exports
`TS_AGENT_PYTHON`, disables user site packages, and clears `PYTHONHOME` for the
entire Pi process tree. `TS_WORKSPACE_ROOT` still identifies only the selected
research workspace.

## Select The Pi Executable

The launcher uses `PI_BIN` when set. Otherwise it resolves `pi` from `PATH`,
which follows the active user's installation and shell configuration. Set an
explicit executable for portable installations:

```bash
export PI_BIN=/absolute/path/to/pi
/path/to/TSPi-installation/TSPi --workspace smoke
```

Verify the selected Pi version is inside the package's supported range. Pi's
extension loader supplies its matching TypeBox runtime.

## Configure Remote Execution

Remote execution is optional. Copy the packaged example into installation
state, then edit only installation-owned values:

```bash
mkdir -p /path/to/TSPi-installation/.pi
cp "$TS_AGENT_SKILL_ROOT/packages/ts-agent-kernel/ts_agent/remote/config.example.toml" \
  /path/to/TSPi-installation/.pi/remote.toml
chmod 600 /path/to/TSPi-installation/.pi/remote.toml
```

The profile owns:

- SSH host alias and SSH config path;
- Torque `qsub`, `qstat`, `qdel`, and `pbsnodes` command names;
- remote workspace root, allowed queues, and resource ceiling;
- software command, activation script, scratch policy, queue restrictions, and
  server-side environment.

Keep SSH keys and authentication in OpenSSH configuration. Calculation requests
select profiles and resources within the configured limits; host paths,
scheduler commands, and software activation come from `remote.toml`.

The launcher flag below is the command-line form of the same read-only
connectivity check exposed in Pi as `/ts-remote status`:

```bash
cd /path/to/TSPi-installation
./TSPi --check-remote
```

Use `/ts-remote doctor` for the full SSH, scheduler, storage, and registered
software chain; `queues` and `nodes` return bounded scheduler views. All four
diagnostics are read-only. Run `doctor` before the first remote calculation.

### Deploy The ASE NEB Runtime With Pixi

`ase.neb` requires a shared cluster-side Python containing ASE, NumPy, and the
same `ts-agent-kernel` release used to prepare the calculation. The repository
ships `config/ase-neb-pixi.toml`; resolve it once, retain its `pixi.lock`, and
install each kernel wheel into a new release directory with `--no-deps`.

The shipped manifest and lock target the `cluster_1w` compute baseline of
Linux 3.10 and glibc 2.18. For another cluster, update the manifest's platform
virtual packages, regenerate the lock on purpose, and derive a new release id
from the manifest, lock, and kernel wheel together.

For example:

```bash
PIXI=/absolute/path/to/pixi
RUNTIME=/home/agent/soft/ase-neb/<release-id>
mkdir -p "$RUNTIME"
cp config/ase-neb-pixi.toml "$RUNTIME/pixi.toml"
cp config/ase-neb-pixi.lock "$RUNTIME/pixi.lock"
"$PIXI" install --locked --manifest-path "$RUNTIME/pixi.toml"
"$RUNTIME/.pixi/envs/default/bin/python" -m pip install \
  --no-deps /path/to/ts_agent_kernel-<version>-py3-none-any.whl
```

Point `[profiles.<name>.software.ase_neb].command` at that environment's
absolute Python path. Set `TS_ASE_NEB_XTB` to the cluster's xTB executable in
the software profile environment. Do not point the profile at an interactive
shell or a Python environment that lacks the matching TSPi runner. The
`ase_neb` doctor check verifies the Python imports and xTB version command.

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
event, subject, summary, and existing report attachments. Configure the
recipient and credentials at installation level. Set `enabled=false` to disable delivery.
Every attachment must be an unchanged member of a generated report package
manifest. To attach a Render result, pass its logical artifact ID to
`ts_report.assetArtifactIds`, then pass the returned `reports/.../assets/...`
reference to `ts_notify`.

The configured recipient applies to subsequent notifications. When the requested
address differs, update the installation configuration before sending. If a
provider's delivery result is unknown, check its status before retrying.

## Configure TS Phone

Select TS Phone in `install.sh`, or pass `--with-phone` in a non-interactive
installation. The wizard builds the server from GitHub and creates
`.pi/ts-phone/server.env` with the installation's workspace, state, and bridge
paths. Edit this file to change the port or other service settings.

When using the wizard's systemd user service:

```bash
systemctl --user start ts-phone-tspi.service
systemctl --user status ts-phone-tspi.service
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
The installation wizard can enable and start the service. Configure FRP, HTTPS,
and phone access for your deployment. `TSPhoneCtl` targets the configured
state directory. Install the Android client on the device using the
[TS Phone app instructions](https://github.com/iawnix/ts-phone/blob/main/docs/artifacts.md).
For a Package that includes an APK, its location is recorded in
`components.phone.mobile_artifact.path` in the selected Package manifest.

The wizard selects source-built Phone servers through `.pi/ts-phone/current`.
`TSPhoneServer` and `TSPhoneCtl` resolve that selection and share the same
configuration as the terminal. The active release's `installation.json` records
its GitHub origin, commit, server version, protocols, and runtime file hashes.

Install the signed Android client from the matching
[TS Phone GitHub Release](https://github.com/iawnix/ts-phone/releases). Use the
`arm64-v8a` APK on ordinary current phones. The release page includes its
checksum, source attestation, and the `ts-phone-component-*.tgz` archive used
by a complete TSPi package.

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

### Native Pi App Server (Experimental)

The App Server uses the repository's exact Pi source pin rather than whichever
`pi` executable is on `PATH`. Prepare that checkout once from the selected
Agent package:

```bash
cd /path/to/TSPi-installation
AGENT_ROOT="$(readlink -f .pi/packages/tspi/current/agent)"
python3 "$AGENT_ROOT/scripts/prepare_pi_source.py" --clone /path/to/pi-source
cd /path/to/pi-source
npm ci --ignore-scripts
npm run hydrate:model-data
```

Start a server for one existing workspace. Read-only is the default:

```bash
cd /path/to/TSPi-installation
export TSPI_PI_SOURCE=/path/to/pi-source
./TSPi --app-server --workspace reaction-a
```

The server prints its ID and Unix socket. Connect Pi's TUI from another
terminal, optionally selecting a session:

```bash
export TSPI_PI_SOURCE=/path/to/pi-source
./TSPi --app-client --connect unix:///path/printed/by/server
./TSPi --app-client --connect unix:///path/printed/by/server \
  --session-id <session-id>
```

A read-only Worker exposes only `read`, `sys_prompt`, `ts_state`, and `ts_remote`. Add
`--allow-writes` to the server command to acquire the workspace directory guard
and exclusive Root lock before exposing `write`, `bash`, and the complete
native TSPi tool set. A conflicting Root writer causes startup to fail; the
launcher never downgrades to read-only implicitly. Server state and sessions
remain under `workspaces/reaction-a/.pi/app-server/`, separate from standalone
and Phone Host history. Stopping the server releases its inherited locks.

The source transport and command remain experimental. Use the Unix socket
locally or through an SSH-forwarded workflow; do not expose it as a production
network service.

The client reads `<installation>/.pi/ts-phone/server.env`; exported
`TS_PHONE_HOST`, `TS_PHONE_PORT`, and `TS_PHONE_STATE_DIR`
override it. The default state directory is `${XDG_STATE_HOME:-~/.local/state}/ts-phone`.
It accepts only loopback HTTP and a user-owned 0600 `auth.token`. This is the
Host connection credential; configure Pi model authentication separately. If
the Host is unavailable, start its service and reconnect. See [Terminal](TERMINAL.md)
for commands, recovery, and integration checks.

The phone app can instead create a managed project/conversation and send a
message. The Host persists the request, then starts or reuses the exact session
when that workspace is idle. Host-only `--phone-worker`, `--lifecycle-preflight`, and
`--lifecycle-guard`, `--session-host-capabilities`, and `--session-writer-check`
syntax is not a supported manual interface. Worker mode
binds an exact session ID and access mode; preflight is a read-only, fail-closed
check. Guard mode excludes every session writer, including Observer, while the
Host deletes data. Guard files are under installation `.pi/session-host/guards/`;
allow this operational state path in the service sandbox, but never remove an
occupied lock file to force access.

Normal Phone and terminal conversations use the same workspace queue, without
a Continue research or read-only-assistant choice. Several clients may read and
submit messages; only one turn runs per workspace. The Host reuses the matching
runtime or transfers an idle Host-owned runtime to the next queued session.
Running, uncertain, or external CLI runtimes are not stopped. Compatibility activation
is retained for standalone diagnostics and clients without queue support. Model authentication
is configured on the TSPi host, separately from the phone connection token.

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
- a complete workspace is validated against the current schemas;
- partial, invalid, or unsupported state produces a diagnostic for recovery.

Preserve the existing records when resolving a startup diagnostic. For a layout
using different schemas, open it with the matching release or start a distinct workspace.

## Run The Research Explorer

`ts_web` is available only when Web was selected and is a read-only process. Keep its registry outside all source
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

For a non-loopback bind, pass `--allow-remote` and configure `--auth-token` or
`TSPI_WEB_AUTH_TOKEN`. The browser prompts for the token after the server
returns its first authentication challenge, keeps it only in page memory, and
adds it as a Bearer credential only to same-origin `/api/` requests. Reloading
the page clears it. Put TLS in front of the service before sending the token
over an untrusted network.

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

1. Validate and build clean Agent and any selected optional components into a new Package.
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
overlays are retained for inspection. Keep the matching
`tspi-package-release/4` manifest and archive together for reinstalling a version.

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
