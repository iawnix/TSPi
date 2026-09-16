# Installation and Operations

This guide installs the TSPi Agent package and its optional TS Web projection.
TS Phone is a separate Flutter application; no TS Phone server, bridge secret,
or local HTTP broker is installed.

## Prerequisites

- Linux with Git and Node.js 22.19+.
- Python 3.11+, Conda/Mamba, and a writable user installation directory.
- A prepared Pi source checkout at the pinned revision (the installer can
  download and patch it automatically).
- Optional: systemd user services and a configured TS Web port.

The installer can use a private SSH checkout or an HTTPS public repository. It
does not need the TS Phone repository.

## Install Or Select A Release

Run `./install.sh` and confirm the installation directory, TSPi revision,
workspace root, Conda root, optional TS Web component, and service policy. Core
Agent, scientific runtime, and molecular rendering are always installed.

The package is selected atomically through:

```text
<install>/.pi/packages/tspi/current -> releases/<release-id>
```

Only the selected release is exposed by the `TSPi` launcher. The installer
records checksums and never executes source outside that release.

## Managed Python Runtime

The scientific runtime is created below `<install>/.agents/envs/tspi` and its
metadata below `<install>/.agents/runtime/tspi`. Runtime caches are private
under `<install>/.pi/runtime-cache`; they can be removed and recreated without
touching workspace data.

The scientific runtime probe executes reaction parsing and an ASE thermal-model
check in addition to geometry and rendering checks. The pinned Pi source runtime
also needs hydrated model data and built workspace dependencies;
`scripts/prepare_pi_source.py --install` prepares both when missing. See
[scientific operations](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md) for capability
discovery, Node pause/resume, and opt-in remote/model smoke commands.

## Configure Remote Execution

Create `<install>/.pi/remote.toml` with an SSH host, scheduler (`torque` or
`direct`), queue, resource limits, and remote software paths. Restrict the file
to mode 0600, then run:

```bash
./TSPi --check-remote
```

Remote execution code and software environments belong to the configured
compute node; the App Server submits and records jobs but does not copy
credentials into the mobile client.

## Configure Notifications

Optional email notifications are configured in `<install>/.pi/notifications.toml`
with mode 0600. The launcher validates the recipient and clawemail root before
the App Server starts. Disable notifications by omitting the file.

## Start The Installation Host

Start one Host for the installation. It owns a single Pi App Server and serves
all validated workspaces below the installation workspace root:

```bash
./TSPi --host
```

With systemd enabled, the same Host is managed as:

```bash
systemctl --user start ts-app-server-tspi.service
```

Attach the native terminal to a project in another shell:

```bash
./TSPi --workspace reaction-a
```

The Host identity is `<install>/.pi/app-server-host/server-id`; its native
session directory is `<install>/.pi/app-server-host/sessions`. Each session
still runs with the selected project's own cwd and is restricted to a direct
child of `<install>/workspaces`.

TS Phone connects once to this Host through Pi Radius, lists the available
projects, and switches project/session inside that connection. Its token and
server UUID are configured in the mobile app and are not stored by TSPi.

## Workspace Bootstrap

The first `./TSPi --app-server --workspace <name>` invocation remains available
as a compatibility mode and creates a 0700 workspace and canonical
scientific files. New installations should start the Host and create projects
through the normal workspace bootstrap path. Bootstrap validates existing JSON
and refuses unsupported state rather than rewriting it.

## Run The Research Explorer

If TS Web was selected, start it with:

```bash
./TSWeb serve \
  --state-dir .pi/ts-web-state \
  --auth-token-file .pi/ts-web/auth.token \
  --source-root workspaces/reaction-a \
  --label "Reaction A" --host 127.0.0.1 --port 8766
```

TS Web is read-only and does not own Pi sessions. Its bearer token is separate
from Pi Radius credentials.

## Upgrade

Run `./install.sh` again and choose the same installation root. The installer
downloads or builds a new content-addressed release, validates its package
inventory, and switches `.pi/packages/tspi/current` atomically. Existing
workspaces, App Server identities, and TS Web credentials are retained.

## Rollback

Select a previous release with the installer rollback option or replace the
`current` pointer with a validated directory under `.pi/packages/tspi/releases`.
Never edit a release in place. Stop affected App Server instances before a
rollback if their package entrypoint changes.

## Operational Recovery

If the Host exits, restart the single Host service. The Root lock is released by
process exit and Pi JSONL sessions remain intact. A terminal or phone reconnect
first receives a fresh session snapshot; prompts are never resent automatically
after an uncertain transport failure.

Inspect the latest installer log under `<install>/.pi/logs/` and verify:

```bash
./TSPi --host
systemctl --user status ts-app-server-tspi.service
```

## Uninstall

Run `./uninstall.sh`. The default preserves workspaces, Pi session history,
credentials, and configuration. Removing the installation root is explicit;
the uninstaller also stops and removes matching App Server and TS Web user
services. There are no Phone server files or bridge secrets to clean up.
