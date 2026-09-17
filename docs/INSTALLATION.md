# Installation and Operations

This guide installs the TSPi Agent package and its optional TS Web projection.
TS Phone is a separate Flutter application; no TS Phone server, bridge secret,
or local HTTP broker is installed.

## Prerequisites

- Linux with Git and Node.js 22.19+.
- Python 3.11+, Conda/Mamba, and a writable user installation directory.
- A prepared Pi source checkout at the pinned revision (the installer can
  download and patch it automatically).
- Optional: systemd user services and a configured TS Web port. Conda/Mamba is
  required when the managed scientific runtime is created; it is not an
  optional backend dependency.

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

Local calculation is available without a remote profile and runs the selected
backend command in a durable Attempt-local subprocess. The input and output
files remain in the local workspace. Choose `execution_target.kind=remote`
only when the calculation should be submitted through the profile below;
remote execution mirrors inputs temporarily and collects results back locally.

Pass `--remote-config /absolute/path/remote.toml` to `install.sh` to validate and
copy a profile into `<install>/.pi/remote.toml`, or create that file manually.
The current remote contract supports Torque/PBS only (`scheduler = "torque"`).
The profile must describe SSH, a writable remote root, allowed queues, and the
site-managed Gaussian/xTB/CREST/ASE-NEB commands. TSPi does not install remote
software. Restrict the file to mode 0600, then run:

```bash
./TSPi --check-remote
```

Remote execution code and software environments belong to the configured
compute node; the App Server submits and records jobs but does not copy
credentials into the mobile client.

### Local backends

Core installation installs the managed Python, RDKit/ASE scientific runtime,
and render tools. It does not download Gaussian or silently install arbitrary
native chemistry programs. Use `--local-config /absolute/path/local.toml` to
select existing executables; the file is copied to `<install>/.pi/local.toml`:

```toml
[backends]
gaussian = "/opt/gaussian/g16"
xtb = "/opt/xtb/bin/xtb"
crest = "/opt/crest/bin/crest"
ase_neb_xtb = "/opt/xtb/bin/xtb"
```

The installer reports command readiness for every local backend. ASE-NEB reuses
the managed Python runtime and only needs a working xTB executable. Gaussian
license checks and site-specific native installation remain administrator work.

## Configure Notifications

Optional email notifications are configured in `<install>/.pi/notifications.toml`
with mode 0600. The launcher validates the recipient and selected transport
before the App Server starts. Disable notifications by omitting the file.

Existing ClawEmail installations remain supported. For direct SMTP delivery,
use an SMTP authorization code from a 163 or QQ mailbox (not the normal
web-login password), and keep it outside the configuration file:

The interactive `install.sh` flow now asks whether to configure email. For a
non-interactive install, the same configuration can be supplied explicitly:

```bash
./install.sh \
  --install-root "$HOME/.local/share/tspi" \
  --non-interactive --yes --service-scope user \
  --email-provider smtp --email-preset qq \
  --email-recipient receiver@example.com \
  --email-username sender@qq.com \
  --email-password-file "$HOME/.config/tspi/qq-smtp-password"
```

The password file must already exist and have mode `0600` for a
non-interactive install. The interactive flow prompts for the authorization
code without echoing it and creates the file automatically below the private
installation state directory. Use `--email-password-env NAME` instead when the
Host service environment provides the secret.

```toml
[notifications.email]
enabled = true
provider = "smtp"
preset = "qq"                 # "163" or "qq"
recipient = "receiver@example.com"
from_address = "sender@qq.com"
username = "sender@qq.com"
password_env = "TSPI_EMAIL_PASSWORD"
```

The SMTP presets use `smtp.163.com` or `smtp.qq.com` on port 465 with implicit
TLS by default. Set `--email-port` and `--email-security starttls` for a
different supported SMTP mode. With `--email-password-env NAME`, the installer
creates a private systemd `EnvironmentFile` when NAME is present in the install
environment; otherwise create `<install>/.pi/email/service.env` before starting
the Host. A private 0600 `password_file` avoids service-environment setup.
POP3 and IMAP are not required for TSPi notifications because this capability
only sends mail.

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

The default and recommended scope is a systemd user unit. A system unit must be
given an explicit `--service-user`; the installer sets `HOME`, `PI_CODING_AGENT_DIR`,
and a private runtime directory so its Host identity and Pi authorization are
usable by the same account as manual `TSPi --host` launches. The user unit
explicitly enables the selected Package server extension set
(`TSPI_SERVER_EXTENSIONS=ts-workflow-native`). The App Server verifies the
manifest and entry digest at each Worker startup. Do not place client code or
an ad-hoc path in this allowlist; development-only experiments belong in
`--standalone`.

Attach the native terminal to a project in another shell:

```bash
./TSPi --workspace reaction-a
```

The Host identity is `<install>/.pi/app-server-host/server-id`; its native
session directory is `<install>/.pi/app-server-host/sessions`. Each session
still runs with the selected project's own cwd and is restricted to a direct
child of `<install>/workspaces`.

TS Phone connects once to this Host through Pi Radius, lists the available
projects, and switches project/session inside that connection. The installer
prints the Host UUID and configured `PI_RADIUS_GATEWAY` (when present) as the
pairing checklist. Phone credentials are held by the mobile secure store and
are unrelated to the TS Web HTTP token.

## Workspace Bootstrap

The first `./TSPi --workspace <name>` invocation creates a 0700 workspace and
canonical scientific files when the named project does not exist. The same
validated bootstrap is used by the compatibility
`./TSPi --app-server --workspace <name>` mode. The Host itself does not create
unnamed projects, and bootstrap validates existing JSON and refuses unsupported
state rather than rewriting it.

## Run The Research Explorer

If TS Web was selected, start it with:

```bash
./TSWeb serve \
  --state-dir .pi/ts-web-state \
  --auth-token-file "$HOME/.local/share/tspi/.pi/ts-web/auth.token" \
  --source-root workspaces/reaction-a \
  --label "Reaction A" --host 127.0.0.1 --port 8766
```

Use `--web-host 0.0.0.0 --allow-remote` only with an authenticated token file;
the installer rejects a non-loopback bind without both explicit settings. TS
Web is read-only and does not own Pi sessions. Its bearer token is separate
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
process exit and Pi JSONL sessions remain intact. Local calculation workers use
independent transient user services when available, so a Host restart does not
normally interrupt them; check the calculation status after recovery. A
terminal or phone reconnect first receives a fresh session snapshot; prompts
are never resent automatically after an uncertain transport failure.

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
