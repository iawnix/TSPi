# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi is a Pi-based computational chemistry research assistant for
transition-state searches and reaction-path analysis. Research state,
evidence, calculations, and reports live in one workspace.

## Install

Prepare Git, OpenSSH, Python 3.11+, Node.js 22.19+, Conda/Mamba, and a Pi
credential. Then run the interactive installer:

```bash
git clone git@github.com:iawnix/TSPi.git
cd TSPi
./install.sh
```

The core installation always includes the Agent, scientific runtime, and
molecular rendering. TS Web is optional. The installer can configure the
per-workspace App Server systemd template; there is no TS Phone daemon to
install.

See [Installation and Operations](docs/INSTALLATION.md) for prerequisites,
runtime setup, upgrades, rollback, and recovery.

## App Server and terminal

Each workspace has one Pi App Server, which owns its sessions, transcript
history, model state, and Root lock:

```bash
./TSPi --app-server --workspace reaction-a
```

The default TSPi command is the local terminal client of that server:

```bash
./TSPi --workspace reaction-a
```

The TS Phone Flutter app connects to the same App Server through Pi Radius;
it is not a second Host or broker. See [Terminal](docs/TERMINAL.md),
[Architecture](docs/ARCHITECTURE.md), and the [TS Phone client guide](https://github.com/iawnix/ts-phone/blob/main/README.md).

## Research and remote execution

Configure SSH/Torque and software profiles in `.pi/remote.toml`, then verify:

```bash
./TSPi --check-remote
```

The skills cover Gaussian, xTB, CREST, ASE-NEB, structure validation,
rendering, reports, and email delivery. See the [Skill Catalog](skills/README.md)
and [Glossary](skills/tspi-orchestration/references/glossary.md).

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
python3 -m unittest discover -s tests -p 'test_*.py'
npm run lint:public
```

The [Maintainer Guide](docs/MAINTAINER_GUIDE.md) describes package validation,
the App Server lifecycle, and release procedure. 中文说明见
[中文架构](docs/ARCHITECTURE.zh-CN.md) 和 [终端文档](docs/TERMINAL.zh-CN.md)。
