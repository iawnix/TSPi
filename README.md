# ResearchAgent

[English](README.md) | [简体中文](README.zh-CN.md)

ResearchAgent is a Pi-based, domain-neutral Research Harness for scientific workflows.
Its bundled skill pack currently focuses on computational chemistry, including
transition-state searches and reaction-path analysis. Research Memory, evidence,
calculations, and reports live in one workspace.

This repository is an active, pre-release project. The supported runtime is the
Native Pi Harness; the retired ordinary-Pi compatibility runtime is not
packaged or selected. The current chemistry bundle is one application of the
domain-neutral research problems, immutable results, execution records and material references.

## Install

Prepare Git, Python 3.11+, Node.js 22.19+, Conda/Mamba, and a Pi credential.
OpenSSH is only needed when using a private SSH repository or remote compute.
Then run the interactive installer:

```bash
git clone https://github.com/iawnix/TSPi.git
cd ResearchAgent
./install.sh
```

For a reproducible non-interactive installation, edit the configuration
variables in `install-configured.sh` (or set its `RESEARCH_AGENT_*` environment
overrides) and run:

```bash
./install-configured.sh
```

Pin `RESEARCH_AGENT_INSTALL_REF` to a full commit SHA when the installation must use an
exact source revision. The wrapper passes compute, name resolver, workspace,
service, Web, Phone, and notification settings to the same installer.

The public Link Relay is provisioned in the same non-interactive run by
default. Its default origin is `https://tsphone.iawnix.xyz`; the installer
creates the Relay service, creates a one-time Host enrollment code, and enrolls
the Host automatically. When the Relay must run elsewhere, set
`RESEARCH_AGENT_WITH_LINK_RELAY=false` and provide an existing enrollment code. The standalone
`install-link-relay.sh` remains available when the Relay must run on a
separate machine.

The core installation includes the Agent and a minimal control runtime.
Scientific computation, validation, and rendering use separately configured
Job environments. TS Web is optional. The installer configures one
installation-wide ResearchAgent Host; there is no TS Phone daemon to install.

Interactive installation also offers the optional ResearchAgent Model Icons font.
Non-interactive installation leaves it disabled unless `--with-model-icons` is
provided; use `--without-model-icons` to disable it explicitly. The font is
installed under the user data directory, and `RESEARCH_AGENT_ICON_STYLE=unicode` or
`RESEARCH_AGENT_ICON_STYLE=nerd` selects the fallback style.

See [Installation and Operations](docs/INSTALLATION.md) for prerequisites,
runtime setup, upgrades, rollback, and recovery. Model/provider behavior is
documented in [Model Compatibility](docs/MODEL_COMPATIBILITY.md).

For the full documentation map, see [Documentation](docs/README.md). Public
Skill entrypoints and their on-demand references are listed in the [Skill
Catalog](skills/README.md).

## Host and terminal

One installation-wide ResearchAgent Host provides authenticated routing, idempotency,
session discovery, and Monitor supervision. Each workspace is owned by one
pinned Pi `SessionWorker`/`durable Harness` lane. The lane owns the agent loop,
model, tools, transcript, and Root lock; the terminal, Phone, and Monitor are
clients of that same lane. Open a workspace directly:

```bash
./research-agent --workspace reaction-a
./research-agent --workspace reaction-a -c
./research-agent --workspace quick-task --mode light
./research-agent --workspace reaction-study --mode research
```

Research Memory organizes original tasks, persistent problem Nodes, immutable Results and explicit relations. Repeated attempts stay with their question. Job Runtime and Artifact Store own execution and materials; research status does not gate tools. The breaking refactor is being validated; see the [implementation plan](docs/RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md).

The first command creates a Harness conversation; the second continues the
latest writable conversation in that workspace. ResearchAgent asks Host for a local Pi
connection descriptor and then starts Pi's official native remote client/TUI.
The default path has no tmux, PTY scraping, or second agent loop. If the Host
is unavailable, ResearchAgent reports the failure. Native Pi Harness is the only
supported runtime backend; the retired ordinary-Pi backend is rejected.
The installer creates, enables, and starts a user-scoped Host by default. Use
`systemctl --user stop|restart|status ts-app-server-research-agent.service` for a
user-scoped installation, or omit `--user` for a system-scoped installation.
The Host is required by the terminal, Phone, and Monitor; `--service-scope none`
is reserved for low-level package staging or tests and leaves normal workspace
entrypoints unavailable. `--host` is an internal service entrypoint and is not
part of normal operation.

The TS Phone Flutter app reaches the same Host and Pi Harness lane through ResearchAgent Link. The
Phone and Host both open outbound WSS connections to a ResearchAgent Link Relay; the Relay
handles device authorization and opaque byte forwarding, not sessions or
research state. See [ResearchAgent Link](docs/RESEARCH_AGENT_LINK.md),
[Terminal](docs/TERMINAL.md), [Architecture](docs/ARCHITECTURE.md), and the
[TS Phone client guide](https://github.com/iawnix/ts-phone/blob/main/README.md).

## Research and remote execution

Configure execution platforms in the installation configuration (or pass one to
the installer with `--compute-config`). Verify a remote platform with:

```bash
./research-agent --check-remote
```

The Job Runtime is the single lifecycle for local and remote targets. Skills
construct input files and commands with ordinary shell and filesystem tools,
then call `job_start` and collect raw output with `job_collect`. `job_probe`
only inspects an execution platform; it never gates an Agent action. Parsed
domain values are optional Skill results and are recorded through
`artifact_register`, Node notes through `research_update`, and useful conclusions through `research_result`.

Skills cover Gaussian, xTB, CREST, ASE-NEB, and structure validation. A Skill
describes commands and parsers; it does not claim that a program is installed.
See [Scientific Capabilities Operations](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.md).

## Browser explorer

TS Web is an optional read-only workspace explorer. When selected during
installation it is available as `TSWeb`; its token and state remain under the
installation's `etc/web*` directories.

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
