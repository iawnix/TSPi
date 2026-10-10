# Installation and Operations

[English](INSTALLATION.md) | [简体中文](INSTALLATION.zh-CN.md)

This guide installs the ResearchAgent Agent package, its optional TS Web browser, and,
when requested, the public ResearchAgent Link Relay. TS Phone is a separate Flutter
application. The Relay remains an independent service and installation root,
but the main installer can provision it and enroll the Host in one run.

## Prerequisites

- Linux with Git and Node.js 22.19+.
- `rg` (ripgrep) and `fd` (or `fdfind`) on the Host service PATH. The installer reports their resolved paths and versions; the Worker checks them before registering the seven native tools. Install system software under `/home/iaw/soft` on this machine and keep test installations under `local_debug/`.
- Python 3.11+, Conda/Mamba, and a writable user installation directory.
- A prepared Pi source checkout at the pinned revision (the installer can
  download and patch it automatically).
- A systemd user or system service is required for a normal installation; a configured TS Web
  port is optional. Conda/Mamba is required when the managed control runtime is created; it is
  not an optional backend dependency.

The bootstrap uses the public HTTPS repository by default and retries interrupted
Git transfers before falling back to a regular shallow clone. It can also use a
private GitHub SSH checkout when passed explicitly; it does not need the TS Phone
repository:

```bash
./install.sh --research-agent-repo git@github.com:your-org/ResearchAgent.git
```

## Install Or Select A Release

Run `./install.sh` and confirm the installation directory, ResearchAgent revision,
workspace root, Conda root, optional TS Web component, and service policy. Core
Agent and its control runtime are always installed. A fresh installation without
job.toml also prepares the local structure/validation environment. Other scientific
environments are selected explicitly; existing bindings are preserved.

The repository has two public entrypoints: `install.sh` and `uninstall.sh`.
Installation defaults to GitHub; use `--source local` for the current checkout or
`--source-root /absolute/path` for another local checkout. GitHub branches, tags,
and commits are selected with `--research-agent-ref`. Local installs use HEAD and
reject uncommitted changes unless `--allow-dirty` is explicitly supplied for local validation.

```bash
./install.sh --source local --config-dir "$PWD/config" \
  --install-root "$HOME/ResearchAgent" --non-interactive --yes
```

The private configuration directory can contain `job.toml`, `models.json`,
`auth.json`, `email.toml`, and `name-resolver.toml`. Missing files preserve installer
defaults or existing installation state. CLI options override `RESEARCH_AGENT_*`
environment defaults and directory inputs. Add `--dry-run` for a redacted preview
without downloads, credential copies, or service changes. GitHub installs also
read credentials from the caller's local directory; that directory is never uploaded.

Phone/Relay access is opt-in. Use `--with-link-relay --link-url https://your-domain`
to provision or reuse a local Relay after Core installation and enroll the Host.
Relay code defaults to `<install>/runtimes/link-relay`, and state to
`<install>/var/state/link-relay`. Options include `--link-relay-root`, `--relay-state-dir`,
`--relay-listen`, `--relay-port`, and `--relay-service-scope`. New loopback Relays
redeem enrollment locally; override with `--link-enrollment-url` when needed.
To use an external Relay, supply `--phone-access link --link-url https://your-domain
--link-enrollment-code <code>`. Standalone management uses `./install.sh relay` and
`./uninstall.sh relay`; see their `--help` output.

For non-interactive installation, `--workspace-root /absolute/path` selects the
directory containing named projects. The default is `<install>/workspaces`.
The installer records it in `etc/installation.json`; the Host, terminal,
TS Web service, and uninstaller consume that same value.

In the interactive installer, `Review and install` displays the complete installation plan.
Press Enter or enter `Y` to start; enter `N` to return to the configuration menu and continue
editing. No installation files are written and no services are started before confirmation.
Choose `9) Quit` to leave the installer without installing.

The package is selected atomically through:

```text
<install>/current -> releases/<release-id>
```

Only the selected release is exposed by the `ResearchAgent` launcher. The installer
records checksums and never executes source outside that release.

### Optional model icon font

The installer can add the small ResearchAgent Model Icons font for branded model icons
in the terminal status bar. Interactive installs ask this question (default
yes); non-interactive installs keep the font disabled unless explicitly
requested:

```bash
./install.sh --non-interactive --yes --with-model-icons \
  --install-root "$HOME/.local/share/research-agent"
```

Use `--without-model-icons` to leave the optional component disabled. The font
is installed under the user data directory (`$XDG_DATA_HOME/fonts/research-agent`, or
`$HOME/.local/share/fonts/research-agent`) and the selected release records a private
marker at `<install>/etc/model-icons.json`. It is not necessary to install
Nerd Font: ResearchAgent falls back to the existing Nerd Font glyphs for other icons and
to ordinary Unicode when `RESEARCH_AGENT_ICON_STYLE=unicode` is set. An explicit
`RESEARCH_AGENT_ICON_STYLE=nerd` or `unicode` always overrides the installer choice.
Model glyphs use the supplementary private-use range so glyphs already present
in a terminal's primary Nerd Font cannot shadow the ResearchAgent font.
The installer refreshes the fontconfig cache when `fc-cache` is available;
already-open terminals may need to be restarted to reload their fallback fonts.

## Managed Python Runtime

Host Python environments default to `~/soft/research-agent/host-envs/<installation-id>` and its
metadata below `<install>/var/state/installation/python`. Runtime caches are private
under `<install>/var/cache`; they can be removed and recreated without
touching workspace data.

Host installation uses the exact Conda builds in `environment.lock.txt` without
solving `environment.yml` again. The base identity includes both files; the Python
overlay identity binds the base and release payload. The Host probe checks JSON
Schema, version constraints, and the installed wheel's origin. Scientific
dependencies are declared by execution catalog entries and verified on their local or
remote `job.toml` targets. The pinned Pi source runtime
also needs hydrated model data and built workspace dependencies;
`scripts/prepare_pi_source.py --install` prepares both when missing. See
[scientific operations](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) for capability
discovery, Job cancellation and recovery, and opt-in remote/model smoke commands.

The same step verifies the pinned Pi runtime and its documented ResearchAgent patch set.
The runtime uses the new workspace-scoped SQLite session layout described below.

## Configure execution targets

Local Jobs run in independent systemd user services. SSH/Torque or PBS targets
stage inputs and return declared outputs. All targets use
`job_start/job_status/job_collect`; select a configured environment with the
Job's `platform` field. No implicit local fallback or remote alias is added.

Copy `config/job.example.toml`, edit target paths and bindings, and pass it
with `--job-config /absolute/path/job.toml`. The installation keeps its private
copy at `<install>/etc/job.toml`. SSH credentials remain in SSH configuration.
ResearchAgent does not install site-managed Gaussian or xTB binaries.

The same installer prepares scientific environments from the domain's pinned
`environments/manifest.json`. Profiles are `structure` (RDKit/NumPy, shared with
validation), `pyscf` (CF22D), `render`, and `wrapper` (Python for already configured
Gaussian/xTB programs). The native programs must already exist on their targets.

```bash
./install.sh --source local --install-root "$HOME/ResearchAgent" \
  --job-profile local:structure --job-profile local:pyscf \
  --job-software-root local=/home/iaw/soft/research-agent/job-envs/my-install \
  --non-interactive --yes
```

Local stores default to `~/soft/research-agent/job-envs/<installation-id>`.
`--without-default-job-environment` creates a control-only fresh installation.
Use `--job-offline` with prepopulated Conda/pip caches. Matching environments are
reused; changed locks select new prefixes. Operator-edited bindings are verified
without being replaced. Locks and receipts live in persistent target stores.

To provision a configured SSH target named `cluster`, add:

```bash
--job-config /absolute/job.toml --job-profile cluster:structure \
--job-software-root cluster=/remote/shared/research-agent/envs \
--job-conda cluster=/remote/conda/bin/conda
```

The remote store must be visible on compute nodes. The SSH host needs Python
3.11+, Conda and `timeout`; queued jobs use the configured PBS/Torque queue.
Remote provisioning sends only helper code, locks and selected target bindings.
Generated remote resolver caches use remote paths. Host model and email credentials
are not copied. Current shipped locks target Linux x86_64: glibc >=2.28 for science
and rendering, >=2.17 for wrapper. Offline targets need prepared package caches.

Local targets are verified automatically. A selected remote profile is provisioned
and verified; `--verify-job-target cluster` verifies an existing remote binding.
Other remote targets are preserved and reported as `not_verified` without SSH calls.
`--job-check-timeout` bounds each acceptance Job including queue wait (default 180s).
Acceptance runs ordinary Jobs: structure checks/XYZ generation, and small calculations
or rendering for configured domain backends. Results are collected; remote test
directories are removed only after completion or confirmed cancellation. Pending
cancellation fails acceptance and retains the job receipt for follow-up.

Readiness distinguishes configuration, environment and execution checks. External
name services are `not_checked`; installation's offline tests do not call PubChem,
OPSIN, models or email. Names normally resolve on local before sending structures
to remote computation. The active bindings remain in `etc/job.toml`; ownership and
acceptance records are in `var/state/installation/job-environments.json` and
`job-readiness.json`. A maintenance import probe remains available with:

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.environment_check --config "$RESEARCH_AGENT_JOB_CONFIG"
```

A complete release package uses the same workflow, without fetching source:

```bash
./install.sh --source package --package-manifest /absolute/research-agent-package-release.json \
  --install-root "$HOME/ResearchAgent" --non-interactive --yes
```

## Installation Logs

Every install or update keeps an owner-only diagnostic log at
`<install>/var/log/install.YYYY.MM.DD.log`. Repeated runs on the same day are
appended with a UTC run separator. The log records installer output, selected
paths, release and service status, backend configuration status, and failure
details, but never prints TS Web tokens, SMTP authorization codes, or SSH keys.
Failed package steps also retain a separate
`install-failure-<timestamp>.log` in the same directory.

## Configure Notifications

Optional email notifications are configured in `<install>/etc/email.toml`
with mode 0600. The launcher validates the recipient and selected transport
before the App Server starts. Disable notifications by omitting the file.

With `./install.sh --config-dir /absolute/path/config`, optional email settings
come from `email.toml` in that directory; see `config/email.example.toml`.
The installer has no built-in sender or recipient. Authorization codes are
referenced through `password_file` (relative to the config directory) or
`password_env`. An absent file or `enabled = false` supplies no email settings:
fresh installs leave email disabled, while updates preserve existing settings.

Existing ClawEmail installations remain supported. For direct SMTP delivery,
use an SMTP authorization code from a 163 or QQ mailbox (not the normal
web-login password), and keep it outside the configuration file:

The interactive `install.sh` flow now asks whether to configure email. For a
non-interactive install, the same configuration can be supplied explicitly:

```bash
./install.sh \
  --install-root "$HOME/.local/share/research-agent" \
  --non-interactive --yes --service-scope user \
  --email-binding smtp --email-preset qq \
  --email-recipient receiver@example.com \
  --email-address sender@qq.com \
  --email-password-file "$HOME/.config/research-agent/qq-smtp-password"
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
password_env = "RESEARCH_AGENT_EMAIL_PASSWORD"
```

The SMTP presets use `smtp.163.com` or `smtp.qq.com` on port 465 with implicit
TLS by default. A different SMTP server can be configured with
`--email-preset custom --email-host mail.example.org`, plus `--email-port` and
`--email-security`. With `--email-password-env NAME`, the installer
creates a private systemd `EnvironmentFile` when NAME is present in the install
environment; otherwise create `<install>/etc/secrets/service.env` before starting
the Host. A private 0600 `password_file` avoids service-environment setup.
POP3 and IMAP are not required for ResearchAgent notifications because this capability
only sends mail.

## Start The Installation Host

The installation owns one ResearchAgent Host for all validated workspaces below the
installation workspace root. The Host is a control plane and the installation
Pi App Server owns one pinned `SessionWorker`/`durable Harness` lane per active
session. The installer enables and starts the Host before reporting success;
the normal terminal launch then attaches to that service:

```bash
./research-agent --workspace reaction-a
```

Use `systemctl --user stop|restart|status ts-app-server-research-agent.service` for a
user-scoped installation, or omit `--user` for a system-scoped installation.
The Host is required by the terminal, Phone, and background Monitor. Service
scope `none` is reserved for low-level package staging or tests and leaves
normal workspace entrypoints unavailable. The generated unit invokes ResearchAgent's
internal service entrypoint; ordinary users do not run `research-agent --host`.

The default and recommended scope is a systemd user unit. A system unit must be
given an explicit `--service-user`; the installer sets `HOME`, `PI_CODING_AGENT_DIR`,
and a private runtime directory so the Host identity and local Pi connection
are usable by the same account as the service user. The Host worker,
tool assembly, and native client are selected from the validated
Package release.

## Services Created By The Installer

The service list depends on the selected scopes and optional components:

| Component | Unit | Created when |
| --- | --- | --- |
| ResearchAgent Host | `ts-app-server-research-agent.service` | `--service-scope user` or `system` |
| TS Web | `ts-web-research-agent.service` | `--with-web` and a Host service scope |
| Link Relay | `research-agent-relay.service` | `--with-link-relay` and `--relay-service-scope user` or `system` |

`--*-service-scope none` installs files and configuration without registering
that component's systemd unit. Host Monitor and session workers are managed by
the Host; they are not additional permanent units. TS Phone is a separate
Flutter client and does not create a service on the installation host.

## research-agent And The Internal App Server

`research-agent` opens a terminal connected to the installation Agent Server.
Manage that server through systemd:

```bash
systemctl --user start ts-app-server-research-agent.service
```

The generated unit invokes the private `current/agent/libexec/research-agent-host`
entrypoint with an explicit installation root. There is no public `research-agentServer` command. Host API, Pi SDK Harness, Monitor,
and session workers belong to this one Agent Server. Pi owns the Agent loop,
model/tool calls and durable transcripts; ResearchAgent supplies Research Memory context and tools.

The fixed Pi checkout lives at `<install>/runtimes/pi/<commit>`.
Session storage is installation-owned; separate runtime injection, HTTP session
stores and `.pi/research-agent/server.json` configuration have been removed.

Create a new conversation or continue the latest conversation in a project:

```bash
./research-agent --workspace reaction-a
./research-agent --workspace reaction-a -c
```

The Host identity is `<install>/var/state/host/server-id`; request receipts,
internal producer identity, Monitor health, and the canonical Pi SQLite durable session repository
live below the same directory. Each session is stored under `var/state/pi/sessions/<workspace-id>/<session-id>/` with `meta.json` and `session.sqlite`. Workspace `.pi/sessions` files are not accepted by
Native Pi Harness. A workspace is restricted to a validated direct child of the
configured workspace root.

The default terminal path uses Pi's official native remote client over the
local descriptor returned by Host. It does not require tmux or PTY scraping.
Host restart preserves SQLite durable transcript, operation/queue IDs, receipts, and
Monitor outbox state; reconnecting clients resume from a Host epoch/cursor.

TS Phone connects to this Host through ResearchAgent Link. During installation, enable
Phone access and provide the HTTPS ResearchAgent Link Relay origin plus a single-use Host
enrollment code created by the Link Relay administrator. Interactive installs
ask for this short-lived code after the long runtime installation, immediately
before writing the Phone manifest, so it cannot expire mid-install. Non-interactive
installs still provide it with `--link-enrollment-code`. The installer writes
`var/state/host/link.json` and the owner-only
`var/state/host/host.token`. The Host then maintains an outbound WSS
connection; no App Server port is exposed to the Relay or Internet.

When a Relay is already installed locally, set `RESEARCH_AGENT_WITH_LINK_RELAY=false`.
The installer discovers known roots (including `/home/iaw/soft/research-agent-link`) and
reads its `research-agent-relay.service` to prefill the Relay origin. Use
`--link-relay-root /path/to/research-agent-link` to select another installation. The
Relay remains a separate service; when provisioned by the unified installer its
lifecycle is tracked by an ownership marker.

The marker is stored at `<install>/etc/link-relay.json`. Uninstall removes the
owned Relay service and code while preserving its database by default. Use
`--purge-relay-state` or `--purge-all` to remove enrollment and device state;
an unmarked shared Relay is never removed by a Host uninstall.
The embedded Relay path is non-interactive so its side effects occur only after
all wrapper configuration has been explicitly supplied.

After the Host is online, create and manage Phone authorization with:

```bash
./research-agent phone pair
./research-agent phone devices
./research-agent phone revoke <device-id>
```

An internal client can use the SSH transport to reach a remote Host. The remote
installation must include `apps/agent/transport/ssh.mjs`; the client
starts that proxy over SSH for both Host and Pi sockets, without opening a
public TCP listener. OpenSSH performs host-key verification while ResearchAgent still
performs `research-agent-host/2` protocol negotiation. Use `--ssh-option` for repeatable
OpenSSH options such as `-i`.

The installer can persist this profile for later `research-agent --workspace`
invocations:

```bash
./scripts/install_wizard.py --non-interactive --yes \
  --install-root /home/iaw/research-agent \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/research-agent/host.sock \
  --remote-proxy-path /opt/research-agent/apps/agent/transport/ssh.mjs \
  --ssh-config /home/user/.ssh/config \
  --ssh-option=-i --ssh-option=/home/user/.ssh/id_ed25519
```

It writes the owner-only `etc/remote-host.json` profile. Command-line
values supplied to `research-agent` override that profile for one launch.

`phone pair` prints the configured ResearchAgent Link Relay URL and an eight-character code that
expires after five minutes and can be used once. TS Phone redeems it for a
revocable device credential held in platform secure storage. Phone credentials
and the Host token are unrelated to the TS Web HTTP token.

Phone is a normal interactive Pi client. Its prompts run through the same Pi
Harness lane and use the same `read`, `write`, `bash`, and ResearchAgent tools as the terminal;
TS Web is the read-only client in this architecture.

## Monitor operations

The Host starts one Monitor worker for the configured workspace root. It polls
durable Compute status and writes registrations, events, and delivery receipts
inside each workspace. `monitor/list`, `monitor/status`, `monitor/enable`, and
`monitor/disable` expose health and backlog. `next_run` persists authenticated execution events until the original session can accept them. Busy or paused sessions leave events pending. Delivery and Pi consumption identities recover retries independently of Memory revision; an accepted input does not mean the science was interpreted. The Agent reads the associated Node and actual Job receipts before recording a conclusion.

The canonical `workspace_manifest.json` identity is verified before Monitor
maps events to the Host route. Its `workspace_id` is the same value used by
Research Memory, local runs, and remote calculation intents; there is no separate
`workspace.json` identity or alias layer.

## Session history

Native Pi Harness accepts only installation-level SQLite durable sessions under
`var/state/pi/sessions/`. Legacy workspace history files are not imported
or resumed. Preserve scientific continuity in Research Memory rather than in a
second session format.

## Workspace Bootstrap

The first `./research-agent --workspace <name>` invocation creates a 0700 workspace and
the canonical `workspace_manifest.json` (`research_workspace/2`) and Research Memory storage when the named project does not exist. Nodes are created on demand under `research/nodes/`; there is no global progress or lifecycle document. The Host's WorkspaceDirectory exposes the same
operation to TS Phone. The Host itself does not create unnamed projects, and
bootstrap validates the canonical protocol and refuses legacy or partial state
rather than rewriting it.

## Run The Research Explorer

If TS Web was selected, start it with:

```bash
./TSWeb serve \
  --state-dir var/state/web \
  --auth-token-file "$HOME/.local/share/research-agent/etc/web/auth.token" \
  --source-root /configured/workspace-root/reaction-a \
  --label "Reaction A" --host 127.0.0.1 --port 8766
```

Use `--web-host 0.0.0.0 --allow-remote` only with an authenticated token file;
the installer rejects a non-loopback bind without both explicit settings. TS
Web is read-only and does not own Pi sessions. Its bearer token is separate
from ResearchAgent Link Host and device credentials.

The installer generates a random TS Web token when the token file is missing.
For a selected token, pass `--web-auth-token` (8-100 URL-safe characters) or
enter one at the hidden interactive prompt. The command-line form can be
visible in shell history or process listings; a pre-created `0600` token file
with `--web-auth-token-file` is preferred for production use.

## Configure Models

Model selection and authentication are provided by the pinned Pi runtime, not
by a separate ResearchAgent provider registry. Built-in and conditional support for GPT,
Gemini, DeepSeek, GLM/Zhipu, Kimi, custom OpenAI-compatible endpoints, and the
non-support boundary for SeedDance/Seedream are listed in
[Model Compatibility](MODEL_COMPATIBILITY.md).

During installation, the installer copies any missing `models.json` and
`auth.json` from the Host service account's `~/.pi/agent/` into the private
installation state at `<install>/etc/pi/`. Existing installation-local files
are preserved on upgrades. If no files are available, configure provider
credentials through Pi or provider environment variables before creating a
ResearchAgent session.

## Upgrade

Run `./install.sh` again and choose the same installation root. The installer
downloads or builds a new content-addressed release, validates its package
inventory, and switches `current` atomically. Model configuration and credentials
are retained. This release accepts only current workspace and session contracts;
use fresh workspaces and sessions when replacing an incompatible release. The
installer does not import or convert previous research state or Web registries.

The installer serializes preparation without fencing the running Host. It prepares
the release, Python environments, Pi and candidate Job acceptance before stopping
managed Host/Web writers for the publication window. Independently owned calculation services keep running.
Configuration and environment checks finish before service startup; readiness
checks verify the selected Host release and the Web State bridge. Keep the
existing service scope when updating an installation.

## Installation Failure Recovery

Before service activation, a caught failure restores the previous program and
configuration snapshot. Once services may have accepted new work, failures keep
the selected release and stop services; rerun the installer to repair forward.
An interrupted installer also requires forward repair because the original
in-memory snapshot is no longer available.

`var/state/installation/maintenance.json` records that boundary without storing
credentials. Normal launch is blocked during unfinished maintenance. This
protects current-version writes; it does not migrate historical data.

## Operational Recovery

For sessions created under the current contract, if the Host exits, restart the single Host service. The Root lock is released by
process exit and Pi SQLite sessions remain intact. Local calculation workers use
independent transient user services when available, so a Host restart does not
normally interrupt them; check the calculation status after recovery. A
terminal or phone reconnect first receives a fresh session snapshot; prompts
are never resent automatically after an uncertain transport failure.

Inspect the latest installer log under `<install>/var/log/` and verify with the
scope selected during installation:

```bash
systemctl --user status ts-app-server-research-agent.service  # user scope
systemctl status ts-app-server-research-agent.service         # system scope
```

## Uninstall

Run `./uninstall.sh`. The default preserves the configured workspace root, Pi session history,
credentials, and configuration. Removing the installation root is explicit;
the uninstaller also stops and removes matching App Server, TS Web, and
installation-owned Link Relay services in the configured scope. A shared or
unmarked Relay is preserved. If a Relay directory was removed manually, run
the standalone Relay uninstaller with its former `--install-root` so the unit
is removed even when its code path no longer exists.

## Scientific binding readiness

The installer records each target's `configuration_validated`, `environment_verified`,
`execution_verified` or `not_verified` status, the checks performed and their scope.
A selected target failing acceptance stops installation before publication. An
unselected remote target remains unverified; no previous success is presented as
fresh evidence. Individual backend imports and versions remain in the detailed report.

`--purge-runtime` removes owned local scientific stores only when no unfinished
recorded Jobs or live processes reference them. External, remote and unowned stores
are retained and listed in the uninstall result.
Ownership of stores created during a failed preparation is also retained for retry
and cleanup. With `--purge-all`, retained external stores still survive removal of
the installation directory; their paths are listed in the result.

Reports and email check/prepare/send/status run through native bash; job_* manages scientific computation. Email retains installation credentials and durable delivery receipts.
