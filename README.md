# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi is a Pi-based computational chemistry research assistant for
transition-state searches and reaction-path analysis. Research state,
evidence, calculations, and reports live in one workspace.

## Install

Prepare Git, Python 3.11+, Node.js 22.19+, Conda/Mamba, and a Pi credential.
OpenSSH is only needed when using a private SSH repository or remote compute.
Then run the interactive installer:

```bash
git clone https://github.com/iawnix/TSPi.git
cd TSPi
./install.sh
```

The core installation always includes the Agent, scientific runtime, and
molecular rendering. TS Web is optional. The installer configures one
installation-wide App Server Host; there is no TS Phone daemon to install.

See [Installation and Operations](docs/INSTALLATION.md) for prerequisites,
runtime setup, upgrades, rollback, and recovery. Model/provider behavior is
documented in [Model Compatibility](docs/MODEL_COMPATIBILITY.md).

## App Server and terminal

One installation-wide Pi App Server Host owns sessions, transcript history,
model state, and the Root lock for all workspaces. Open a workspace directly;
TSPi starts the user service and waits for the Host when it is not running:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

The first command creates a conversation; the second continues the latest
conversation in that workspace.
Use `systemctl --user stop|restart|status ts-app-server-tspi.service` for the
Host lifecycle. `--host` is an internal service entrypoint and is not part of
normal operation.

The TS Phone Flutter app connects to the same App Server through Pi Radius;
it is not a second Host or broker. See [Terminal](docs/TERMINAL.md),
[Architecture](docs/ARCHITECTURE.md), and the [TS Phone client guide](https://github.com/iawnix/ts-phone/blob/main/README.md).

## Research and remote execution

Configure Backends and Compute environments in the unified
`.pi/compute.toml` (or pass one to the installer with `--compute-config`).
Local and remote environments live in that same file. Verify a remote environment with:

```bash
./TSPi --check-remote
```

`ts_calc` is the single calculation lifecycle for both local and remote
targets. A compute environment contains a `kind` (`local` or `remote`) and its
`backends` table; only remote environments add SSH/Torque fields. `/compute` and the
`ts_environment` tool inspect the complete environment catalog; readiness checks
run as part of the bound calculation preflight.

The skills cover Gaussian, xTB, CREST, ASE-NEB, structure validation,
rendering, reports, and email delivery. See the [Skill Catalog](skills/README.md)
and [Glossary](skills/tspi-research-kernel/references/glossary.md).

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
```

The [Maintainer Guide](docs/MAINTAINER_GUIDE.md) describes package validation,
the App Server lifecycle, and release procedure. 中文说明见
[中文架构](docs/ARCHITECTURE.zh-CN.md) 和 [终端文档](docs/TERMINAL.zh-CN.md)。
