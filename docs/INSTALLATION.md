# Installation and Operations

[English](INSTALLATION.md) | [简体中文](INSTALLATION.zh-CN.md)

This guide installs the TSPi Agent package and its optional TS Web browser.
TS Phone is a separate Flutter application. TSPi installs only the Host-side
Link client; the public TSPi Link Relay has its own standalone installer.

## Prerequisites

- Linux with Git and Node.js 22.19+.
- Python 3.11+, Conda/Mamba, and a writable user installation directory.
- A prepared Pi source checkout at the pinned revision (the installer can
  download and patch it automatically).
- Optional: a systemd user or system service and a configured TS Web port. Conda/Mamba is
  required when the managed scientific runtime is created; it is not an
  optional backend dependency.

The bootstrap uses the public HTTPS repository by default and retries interrupted
Git transfers before falling back to a regular shallow clone. It can also use a
private GitHub SSH checkout when passed explicitly; it does not need the TS Phone
repository:

```bash
./install.sh --tspi-repo git@github.com:your-org/TSPi.git
```

## Install Or Select A Release

Run `./install.sh` and confirm the installation directory, TSPi revision,
workspace root, Conda root, optional TS Web component, and service policy. Core
Agent, scientific runtime, and molecular rendering are always installed.

For non-interactive installation, `--workspace-root /absolute/path` selects the
directory containing named projects. The default is `<install>/workspaces`.
The installer records it in `.pi/tspi/workspace-root.json`; the Host, terminal,
TS Web service, and uninstaller consume that same value.

The package is selected atomically through:

```text
<install>/.pi/packages/tspi/current -> releases/<release-id>
```

Only the selected release is exposed by the `TSPi` launcher. The installer
records checksums and never executes source outside that release.

### Optional model icon font

The installer can add the small TSPi Model Icons font for branded model icons
in the terminal status bar. Interactive installs ask this question (default
yes); non-interactive installs keep the font disabled unless explicitly
requested:

```bash
./install.sh --non-interactive --yes --with-model-icons \
  --install-root "$HOME/.local/share/tspi"
```

Use `--without-model-icons` to leave the optional component disabled. The font
is installed under the user data directory (`$XDG_DATA_HOME/fonts/tspi`, or
`$HOME/.local/share/fonts/tspi`) and the selected release records a private
marker at `<install>/.pi/tspi/model-icons.json`. It is not necessary to install
Nerd Font: TSPi falls back to the existing Nerd Font glyphs for other icons and
to ordinary Unicode when `TSPI_ICON_STYLE=unicode` is set. An explicit
`TSPI_ICON_STYLE=nerd` or `unicode` always overrides the installer choice.
Model glyphs use the supplementary private-use range so glyphs already present
in a terminal's primary Nerd Font cannot shadow the TSPi font.
The installer refreshes the fontconfig cache when `fc-cache` is available;
already-open terminals may need to be restarted to reload their fallback fonts.

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

During an upgrade, the same step verifies the complete multi-workspace patch. Older
installations that already have the project-listing portion receive the compatible
incremental patch for project creation and `workspaceId` session binding before the
Host is restarted.

## Configure Remote Execution (Compute Backends)

Local calculation runs the selected backend in a durable Attempt-local
subprocess. Remote execution mirrors inputs temporarily and collects results
back locally. Both are selected from the same compute environment model; only a
remote environment carries SSH/Torque transport fields.

The installer accepts one TOML file for compute backends. During an interactive
install, enter its path when prompted; for a non-interactive install, pass
`--compute-config /absolute/path/compute.toml`. The project template is
`config/compute.example.toml`. Copy it, edit the local and/or remote backend bindings
available on the target machine, and pass the edited file to the installer. The
installed copy is `<install>/.pi/compute.toml` and is written with mode `0600`.

Local and remote calculations share one public lifecycle through `ts_calc`; choose
`execution_target.kind = "local"` or `"remote"` and, when using the unified file,
its environment name in the calculation intent. SSH keys and other credentials stay in
the SSH configuration and are never copied into this TOML. TSPi does not install
Gaussian or other site-managed native chemistry software.

`/compute` and the `compute.environments` command list the configured local and
remote environments. Remote scheduler checks remain available to the execution
layer when a remote calculation is prepared; they are not a separate
remote-only command surface.
Add `--probe-remote` when installation should run `TSPi --check-remote` and fail
unless SSH, the scheduler, writable remote root, and configured software probes
are ready. Without that flag the summary reports `not_probed` rather than
claiming remote readiness.
The current remote contract supports Torque/PBS only (`scheduler = "torque"`).
The environment must describe SSH, a writable remote root, allowed queues, and the
site-managed Gaussian/xTB/CREST/ASE-NEB commands. Restrict the file to mode 0600,
then run:

```bash
./TSPi --check-remote
```

Remote execution code and software environments belong to the configured compute
node; the App Server submits and records jobs but does not copy credentials into
the mobile client.

## Installation Logs

Every install or update keeps an owner-only diagnostic log at
`<install>/.pi/logs/install.YYYY.MM.DD.log`. Repeated runs on the same day are
appended with a UTC run separator. The log records installer output, selected
paths, release and service status, backend configuration status, and failure
details, but never prints TS Web tokens, SMTP authorization codes, or SSH keys.
Failed package steps also retain a separate
`install-failure-<timestamp>.log` in the same directory.

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
  --email-binding smtp --email-preset qq \
  --email-recipient receiver@example.com \
  --email-address sender@qq.com \
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
preset = "qq"                 # "163", "qq", or "custom"
recipient = "receiver@example.com"
username = "sender@qq.com"
password_env = "TSPI_EMAIL_PASSWORD"
```

The SMTP presets use `smtp.163.com` or `smtp.qq.com` on port 465 with implicit
TLS by default. A different SMTP server can be configured with
`--email-preset custom --email-host mail.example.org`, plus `--email-port` and
`--email-security`. With `--email-password-env NAME`, the installer
creates a private systemd `EnvironmentFile` when NAME is present in the install
environment; otherwise create `<install>/.pi/email/service.env` before starting
the Host. A private 0600 `password_file` avoids service-environment setup.
POP3 and IMAP are not required for TSPi notifications because this capability
only sends mail.

## Start The Installation Host

The installation owns one TSPi Host for all validated workspaces below the
installation workspace root. The Host is a control plane and the installation
Pi App Server owns one pinned `SessionWorker`/`AgentHarness` lane per active
session. The installer can enable and start the Host, and a normal terminal
launch starts the configured service when needed:

```bash
./TSPi --workspace reaction-a
```

Use `systemctl --user stop|restart|status ts-app-server-tspi.service` for a
user-scoped installation, or omit `--user` for a system-scoped installation.
With service scope `none`, the managed Host is disabled; Phone and background
Monitor are unavailable. Configure a user or system service when Host-backed
features are needed. The generated unit invokes TSPi's internal service
entrypoint; ordinary users do not run `TSPi --host`.

The default and recommended scope is a systemd user unit. A system unit must be
given an explicit `--service-user`; the installer sets `HOME`, `PI_CODING_AGENT_DIR`,
and a private runtime directory so the Host identity and local Pi connection
are usable by the same account as the service user. The Host worker facet,
server-extension allowlist, and native client are selected from the validated
Package release.

Create a new conversation or continue the latest conversation in a project:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

The Host identity is `<install>/.pi/app-server-host/server-id`; request receipts,
scheduler leases, Monitor health, and the canonical Pi format-4 session repository
live below the same directory. format-4 files are grouped by cwd under
`.pi/app-server-host/sessions/`. Workspace `.pi/sessions` files are legacy format-3
history and remain read-only until an explicit import. A workspace is restricted
to a validated direct child of the configured workspace root.

The default terminal path uses Pi's official native remote client over the
local descriptor returned by Host. It does not require tmux or PTY scraping.
Host restart preserves format-4 transcript, operation/queue IDs, receipts, and
Monitor outbox state; reconnecting clients resume from a Host epoch/cursor.

TS Phone connects to this Host through TSPi Link. During installation, enable
Phone access and provide the HTTPS TSPi Link Relay origin plus a single-use Host
enrollment code created by the Link Relay administrator. The installer writes
`.pi/app-server-host/link.json` and the owner-only
`.pi/app-server-host/host.token`. The Host then maintains an outbound WSS
connection; no App Server port is exposed to the Relay or Internet.

After the Host is online, create and manage Phone authorization with:

```bash
./TSPi phone pair
./TSPi phone devices
./TSPi phone revoke <device-id>
```

`phone pair` prints the configured TSPi Link Relay URL and an eight-character code that
expires after five minutes and can be used once. TS Phone redeems it for a
revocable device credential held in platform secure storage. Phone credentials
and the Host token are unrelated to the TS Web HTTP token.

Phone is a normal interactive Pi client. Its prompts run through the same Pi
Harness lane and use the same `read`, `write`, `bash`, and TSPi tools as the terminal;
TS Web is the read-only client in this architecture.

## Monitor operations

The Host starts one Monitor worker for the configured workspace root. It polls
durable Compute status and writes registrations, events, and delivery receipts
inside each workspace. `monitor/list`, `monitor/status`, `monitor/enable`, and
`monitor/disable` expose health and backlog. Wake and notification channels have
separate leases, retries, and receipts. A wake means that Pi accepted a prompt;
it does not mean that the agent turn completed. The Root Agent must reread
`ts_state` and inspect the calculation before changing ResearchMap.

The stable `ws_<hex>` identity in `workspace.json` is verified before Monitor
maps it to the Host route name (the direct-child directory). This prevents a
foreign event from being delivered to another project.

## Legacy history migration

Workspace format-3 histories remain read-only. Inspect them with
`apps/app-server/tspi-history.mjs`; pass `--import` and an explicit `--source`
to create a new installation-level format-4 session. The source is hash-checked and
preserved, and a provenance report is written under
`.pi/app-server-host/history-imports/`. Active operations, torn files,
unsupported records, and ambiguous workspace ownership are rejected rather than
replayed.

## Workspace Bootstrap

The first `./TSPi --workspace <name>` invocation creates a 0700 workspace and
canonical scientific files when the named project does not exist. The Host's
WorkspaceDirectory exposes the same operation to TS Phone. The Host itself does
not create unnamed projects, and bootstrap validates existing JSON and refuses
unsupported state rather than rewriting it.

## Run The Research Explorer

If TS Web was selected, start it with:

```bash
./TSWeb serve \
  --state-dir .pi/ts-web-state \
  --auth-token-file "$HOME/.local/share/tspi/.pi/ts-web/auth.token" \
  --source-root /configured/workspace-root/reaction-a \
  --label "Reaction A" --host 127.0.0.1 --port 8766
```

Use `--web-host 0.0.0.0 --allow-remote` only with an authenticated token file;
the installer rejects a non-loopback bind without both explicit settings. TS
Web is read-only and does not own Pi sessions. Its bearer token is separate
from TSPi Link Host and device credentials.

The installer generates a random TS Web token when the token file is missing.
For a selected token, pass `--web-auth-token` (8-100 URL-safe characters) or
enter one at the hidden interactive prompt. The command-line form can be
visible in shell history or process listings; a pre-created `0600` token file
with `--web-auth-token-file` is preferred for production use.

## Configure Models

Model selection and authentication are provided by the pinned Pi runtime, not
by a separate TSPi provider registry. Built-in and conditional support for GPT,
Gemini, DeepSeek, GLM/Zhipu, Kimi, custom OpenAI-compatible endpoints, and the
non-support boundary for SeedDance/Seedream are listed in
[Model Compatibility](MODEL_COMPATIBILITY.md).

## Upgrade

Run `./install.sh` again and choose the same installation root. The installer
downloads or builds a new content-addressed release, validates its package
inventory, and switches `.pi/packages/tspi/current` atomically. Existing
workspaces, App Server identities, and TS Web credentials are retained.

## Rollback

The installer has a transaction rollback for failed upgrades: the selected
release, launchers, runtime manifest, credentials, backend files, Phone
manifest, and managed service units are restored together. There is no separate
rollback selector in the current CLI. To move to an older release, run the
installer with the desired pinned revision and let it perform a normal,
validated upgrade; never edit a release directory in place or hand-edit the
`current` pointer.

## Operational Recovery

If the Host exits, restart the single Host service. The Root lock is released by
process exit and Pi JSONL sessions remain intact. Local calculation workers use
independent transient user services when available, so a Host restart does not
normally interrupt them; check the calculation status after recovery. A
terminal or phone reconnect first receives a fresh session snapshot; prompts
are never resent automatically after an uncertain transport failure.

Inspect the latest installer log under `<install>/.pi/logs/` and verify with the
scope selected during installation:

```bash
systemctl --user status ts-app-server-tspi.service  # user scope
systemctl status ts-app-server-tspi.service         # system scope
```

## Uninstall

Run `./uninstall.sh`. The default preserves the configured workspace root, Pi session history,
credentials, and configuration. Removing the installation root is explicit;
the uninstaller also stops and removes matching App Server and TS Web services
in the configured scope. The standalone Link Relay has its own installation and
service lifecycle; it is not removed by the local TSPi uninstaller.
