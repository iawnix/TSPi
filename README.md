# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi is a Pi-based, domain-neutral Research Harness for scientific workflows.
Its bundled skill pack currently focuses on computational chemistry, including
transition-state searches and reaction-path analysis. Research state, evidence,
calculations, and reports live in one workspace.

This repository is an active, pre-release project. The supported runtime is the
Native Pi Harness; the retired ordinary-Pi compatibility runtime is not
packaged or selected. The current chemistry bundle is one application of the
domain-neutral Claims, Nodes, Findings, Gates, Attempts, and Artifacts model.

## Install

Prepare Git, Python 3.11+, Node.js 22.19+, Conda/Mamba, and a Pi credential.
OpenSSH is only needed when using a private SSH repository or remote compute.
Then run the interactive installer:

```bash
git clone https://github.com/iawnix/TSPi.git
cd TSPi
./install.sh
```

For a reproducible non-interactive installation, edit the configuration
variables in `install-configured.sh` (or set its `TSPI_*` environment
overrides) and run:

```bash
./install-configured.sh
```

Pin `TSPI_INSTALL_REF` to a full commit SHA when the installation must use an
exact source revision. The wrapper passes compute, name resolver, workspace,
service, Web, Phone, and notification settings to the same installer.

The public Link Relay is provisioned in the same non-interactive run by
default. Its default origin is `https://tsphone.iawnix.xyz`; the installer
creates the Relay service, creates a one-time Host enrollment code, and enrolls
the Host automatically. When the Relay must run elsewhere, set
`TSPI_WITH_LINK_RELAY=false` and provide an existing enrollment code. The standalone
`install-link-relay.sh` remains available when the Relay must run on a
separate machine.

The core installation always includes the Agent, scientific runtime, and
molecular rendering. TS Web is optional. The installer configures one
installation-wide TSPi Host; there is no TS Phone daemon to install.

Interactive installation also offers the optional TSPi Model Icons font.
Non-interactive installation leaves it disabled unless `--with-model-icons` is
provided; use `--without-model-icons` to disable it explicitly. The font is
installed under the user data directory, and `TSPI_ICON_STYLE=unicode` or
`TSPI_ICON_STYLE=nerd` selects the fallback style.

See [Installation and Operations](docs/INSTALLATION.md) for prerequisites,
runtime setup, upgrades, rollback, and recovery. Model/provider behavior is
documented in [Model Compatibility](docs/MODEL_COMPATIBILITY.md).

For the full documentation map, see [Documentation](docs/README.md). Public
Skill entrypoints and their on-demand references are listed in the [Skill
Catalog](extensions/core/README.md).

## Host and terminal

One installation-wide TSPi Host provides authenticated routing, idempotency,
session discovery, and Monitor supervision. Each workspace is owned by one
pinned Pi `SessionWorker`/`durable Harness` lane. The lane owns the agent loop,
model, tools, transcript, and Root lock; the terminal, Phone, and Monitor are
clients of that same lane. Open a workspace directly:

```bash
./ResearchAgent --workspace reaction-a
./ResearchAgent --workspace reaction-a -c
./ResearchAgent --workspace quick-task --mode light
./ResearchAgent --workspace reaction-study --mode research
```

Light workspaces keep memory and lifecycle state small, while using the same
mode-neutral compute plane as research workspaces: `compute_catalog`,
`compute_readiness`, `compute_run`, and `compute_cancel`. Native results use an
operational execution scope under `nodes/<execution_scope>/attempts/` and the
canonical workspace Artifact paths. Light mode does not create ResearchMap
Claims/Nodes, audited Attempts, scheduler Monitor state, or scientific
interpretations. Use `--mode research` when those
lifecycle guarantees are required, for example for transition-state/IRC
validation or a comparative mechanistic conclusion.

The first command creates a Harness conversation; the second continues the
latest writable conversation in that workspace. TSPi asks Host for a local Pi
connection descriptor and then starts Pi's official native remote client/TUI.
The default path has no tmux, PTY scraping, or second agent loop. If the Host
is unavailable, TSPi reports the failure. Native Pi Harness is the only
supported runtime backend; the retired ordinary-Pi backend is rejected.
The installer creates, enables, and starts a user-scoped Host by default. Use
`systemctl --user stop|restart|status ts-app-server-tspi.service` for a
user-scoped installation, or omit `--user` for a system-scoped installation.
The Host is required by the terminal, Phone, and Monitor; `--service-scope none`
is reserved for low-level package staging or tests and leaves normal workspace
entrypoints unavailable. `--host` is an internal service entrypoint and is not
part of normal operation.

The TS Phone Flutter app reaches the same Host and Pi Harness lane through TSPi Link. The
Phone and Host both open outbound WSS connections to a TSPi Link Relay; the Relay
handles device authorization and opaque byte forwarding, not sessions or
research state. See [TSPi Link](docs/TSPi_LINK.md),
[Terminal](docs/TERMINAL.md), [Architecture](docs/ARCHITECTURE.md), and the
[TS Phone client guide](https://github.com/iawnix/ts-phone/blob/main/README.md).

## Research and remote execution

Configure Backends and Compute environments in the unified
`.pi/compute.toml` (or pass one to the installer with `--compute-config`).
Local and remote environments live in that same file. Verify a remote environment with:

```bash
./ResearchAgent --check-remote
```

`compute_run` is the single calculation lifecycle for both local and remote
targets. A compute environment contains a `kind` (`local` or `remote`) and its
`backends` table; only remote environments add SSH/Torque fields. `/compute` and the
`compute_environment` tool inspect the complete environment catalog; readiness checks
run as part of the bound calculation preflight.

The skills cover Gaussian, xTB, CREST, ASE-NEB, structure validation,
rendering, reports, and email delivery. Discover the exact versioned capability
and environment before execution; a Skill description never proves that a
program is installed. See the [Capability and Compute Model](docs/CAPABILITY_COMPUTE_MODEL.md)
and [Scientific Capabilities Operations](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.md).

## Browser explorer

TS Web is an optional read-only workspace explorer. When selected during
installation it is available as `TSWeb`; its token and state remain under the
installation's `.pi/ts-web*` directories.

## Uninstall

Run the installer-provided uninstaller and choose whether to retain workspaces,
Pi sessions, configuration, and managed runtime state:

```bash
./uninstall.sh
```

## Development

Use the project checks from the source checkout:

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
python3 tools/test/runner.py source -- -q
npm run lint:public
npm run lint:skills
```

The [Maintainer Guide](docs/MAINTAINER_GUIDE.md) describes package validation,
the App Server lifecycle, and release procedure. 中文说明见
[中文架构](docs/ARCHITECTURE.zh-CN.md) 和 [终端文档](docs/TERMINAL.zh-CN.md)。

## Community And Project Policy

- [Contributing](CONTRIBUTING.md) / [贡献指南](CONTRIBUTING.zh-CN.md)
- [Security policy](SECURITY.md) / [安全策略](SECURITY.zh-CN.md)
- [Code of Conduct](CODE_OF_CONDUCT.md) / [行为准则](CODE_OF_CONDUCT.zh-CN.md)
- [Changelog](CHANGELOG.md) / [变更日志](CHANGELOG.zh-CN.md)

Project-owned source in this repository is licensed under the [Apache License
2.0](LICENSE). Third-party dependencies, the pinned Pi source, native chemistry
programs, and bundled assets may have separate licenses; preserve their notices
when redistributing them.
