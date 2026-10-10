# CoRAgent

[English](README.md) | [简体中文](README.zh-CN.md)

CoRAgent (Computational Research Agent) is an AI research assistant that helps plan studies, run calculations,
analyze results, and write reports with traceable evidence. Its skills cover
computational chemistry: molecular structures, transition-state searches,
reaction paths, and energy comparisons. Research notes and results stay in a
workspace so you can return to a study and continue where you left off.

## What it does

- Select methods, prepare inputs, and run tasks locally or on configured remote compute platforms.
- Analyze structures, frequencies, and reaction paths; record conclusions, evidence, and open questions.
- Turn calculation results into reports with molecular images, data tables, and energy plots.
- Work in the terminal, connect to the same workspace with CoRHub, or browse research records with optional CoRAgent Web.

Set up the scientific software and execution environments for your calculations
with the [Scientific operations guide](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.md).

## Install

Prepare Git, Python 3.11+, Node.js 22.19+, Conda/Mamba, and model credentials, then run:

```bash
git clone https://github.com/iawnix/coragent.git
cd coragent
./install.sh
```

To upgrade an existing deployment to 0.19, install in a new directory, update to
the matching CoRHub client, and pair your devices again. Follow the
[cutover guide](docs/CORAGENT_CUTOVER.md) for backup and migration steps.

For non-interactive installation, prepare private files using the templates in `config/`, then run:

```bash
./install.sh --source local --config-dir "$PWD/config" \
  --install-root "$HOME/CoRAgent" --non-interactive --yes
```

See [Installation and Operations](docs/INSTALLATION.md) for model configuration,
remote compute, phone connections, and service management.

## Start a study

Open a workspace:

```bash
./coragent --workspace reaction-study
```

Describe your research question, available materials, and desired results in the
terminal. To continue the latest conversation later:

```bash
./coragent --workspace reaction-study -c
```

The installer configures the workspace service. See [Terminal](docs/TERMINAL.md)
for session controls and [CoRAgent Link](docs/CORAGENT_LINK.md) for phone access.

## Documentation

- [Documentation index](docs/README.md)
- [Skill catalog and loading language](skills/README.md)
- [Scientific and remote execution](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.md)
- [Model compatibility](docs/MODEL_COMPATIBILITY.md)
- [Architecture](docs/ARCHITECTURE.md) ([简体中文](docs/ARCHITECTURE.zh-CN.md)) and [Maintainer guide](docs/MAINTAINER_GUIDE.md)

## Development

From the source checkout:

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
npm run lint:public
npm run lint:skills
```

Keep test environments, caches, and evidence in the private local `local_debug/`
directory, excluded from commits and packages. See the [Maintainer guide](docs/MAINTAINER_GUIDE.md)
for test preparation and complete checks.

## Uninstall

```bash
./uninstall.sh
```

The uninstaller asks whether to retain workspaces, sessions, configuration, and managed runtimes.

## Community and license

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Changelog](CHANGELOG.md)

Project source is licensed under [Apache License 2.0](LICENSE). Consult the licenses
provided with third-party dependencies, Pi source, scientific software, and bundled assets for their terms.
