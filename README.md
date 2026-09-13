# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi is a computational chemistry research assistant built on Pi, focused on
transition-state searches and reaction-path analysis. Describe a research
question in natural language to get help preparing calculations, submitting
remote jobs, and interpreting results. Research history, supporting evidence,
and reports stay together in a project workspace.

## Features

- Generate initial molecular structures from SMILES, or import existing XYZ and Gaussian inputs.
- Use Gaussian, xTB, CREST, and other tools for geometry optimization, frequency analysis, conformer searches, and reaction-path studies.
- Submit remote calculations through SSH and Torque, check progress, and collect and parse results.
- Track hypotheses, calculation attempts, failures, and validation results to resume research, compare approaches, and trace conclusions.
- Render molecular structures, reaction-path animations, energy profiles, and scan curves, and generate research reports.
- Continue research from a terminal or phone, and explore progress and results in a browser.

## Install

Prepare a Linux host with Git, OpenSSH, Python 3.11+, Node.js 22.19+, Conda or
Mamba, and Pi with a configured model and credentials. See the full
[prerequisites](docs/INSTALLATION.md#prerequisites).

Run the installation wizard:

```bash
curl -fsSL https://raw.githubusercontent.com/iawnix/TSPi/main/install.sh | bash
```

Choose the installation directory, Conda location, TS Web and TS Phone
components, and systemd services in the wizard. Selecting TS Phone downloads
its source from GitHub, builds the server, and configures phone access and
shared terminal sessions. You can choose a branch, tag, or commit for TSPi and
TS Phone; both default to `main`. Add `--with-render` to the installer arguments
to include molecular visualization dependencies.

See [Installation and Operations](docs/INSTALLATION.md) for non-interactive
installation, service configuration, and upgrades.

## Start Research

After installation, open the installation directory and start a research
session directly in the terminal:

```bash
cd /path/to/TSPi-installation
./TSPi --standalone --workspace reaction-a
```

Projects are stored under the installation's `workspaces/` directory. Start by
importing an existing input and describing the research goal, for example:

> Check this Gaussian input and plan a transition-state optimization, frequency
> calculation, and IRC validation. Once the calculations finish, summarize the
> evidence for the structure, energy, and reaction-path connectivity in a report.

Before running remote calculations, configure the SSH host, queue, resources,
and software in the installation's `.pi/remote.toml`, then check the connection:

```bash
./TSPi --check-remote
```

See [remote execution setup](docs/INSTALLATION.md#configure-remote-execution)
for configuration examples. The result collection step downloads selected
output files into the workspace for local parsing.

## Phone And Shared Sessions

[TS Phone](https://github.com/iawnix/ts-phone) provides an Android client.
Connect it to the server to browse conversations, send messages, and continue
research. A terminal can join the same conversation.

The installer sets up the Phone server on your TSPi host. Install the Android
client on your phone using the [app instructions](https://github.com/iawnix/ts-phone/blob/main/docs/artifacts.md).

If you configured a systemd user service during installation, start it and
open the terminal:

```bash
systemctl --user start ts-phone-tspi.service
cd /path/to/TSPi-installation
./TSPi --workspace reaction-a
```

Reconnect to the latest conversation:

```bash
./TSPi --workspace reaction-a --continue
```

Research hosted by the service can keep running after you exit the shared
terminal. See [Phone configuration](docs/INSTALLATION.md#configure-ts-phone)
for connection settings and [Terminal](docs/TERMINAL.md) for conversation
controls and keyboard shortcuts.

## Explore In A Browser

TS Web displays the research roadmap, calculation records, scientific
conclusions, validation results, and files. Explore branches and dependencies
on the research map, then open a node to inspect its calculations.

If you selected TS Web during installation, you can start it manually:

```bash
/path/to/TSPi-installation/TSWeb serve \
  --state-dir /path/to/TSPi-installation/.pi/ts-web \
  --source-root /path/to/TSPi-installation/workspaces/reaction-a \
  --label "Reaction A" \
  --host 127.0.0.1 \
  --port 8766
```

Open [http://127.0.0.1:8766/](http://127.0.0.1:8766/) in a browser on the host.
See [browser server setup](docs/INSTALLATION.md#run-the-research-explorer) for
multiple workspaces and remote access.

## Uninstall

The installation includes an uninstaller:

```bash
/path/to/TSPi-installation/uninstall.sh --install-root /path/to/TSPi-installation
```

Follow the prompts to choose whether to remove workspaces, sessions,
configuration, and runtime environments. Research data and credentials are
kept by default. See [uninstall options](docs/INSTALLATION.md#uninstall).

## Documentation

- [Installation and Operations](docs/INSTALLATION.md): dependencies, configuration, services, upgrades, and removal.
- [Terminal](docs/TERMINAL.md): projects, conversations, keyboard shortcuts, and recovery.
- [Skill Catalog](skills/README.md): transition-state searches, calculation methods, structure validation, visualization, and reports.
- [Glossary](skills/tspi-orchestration/references/glossary.md): terminology used in research records.
- [Architecture](docs/ARCHITECTURE.md) / [中文架构](docs/ARCHITECTURE.zh-CN.md): system design and data model.
- [Maintainer Guide](docs/MAINTAINER_GUIDE.md): source layout, testing, and releases.

## Development

Install the Node dependencies and run checks from the source checkout.
Python tests require the scientific Python environment:

```bash
npm ci
npm run typecheck
npm run test:fast
npm run test:package
npm run test:terminal
npm run lint:public
```

See [development setup](docs/MAINTAINER_GUIDE.md#development-setup) and
[validation tiers](docs/MAINTAINER_GUIDE.md#validation-tiers) for environment
preparation and the complete test suite.
