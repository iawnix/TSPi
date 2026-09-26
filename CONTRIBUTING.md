# Contributing to TSPi

Thank you for helping improve TSPi. The project is a domain-neutral Research
Harness with a computational-chemistry skill bundle. Contributions should keep
the Harness lifecycle, ResearchMap authority, and registered capability
contracts explicit.

## Before Opening A Change

- Search existing issues and documentation before starting a broad refactor.
- Keep one change focused. Describe the user-visible behavior and the contract
  that owns it.
- Do not add a second state store, agent loop, Pi runtime, or public tool alias.
- Do not commit credentials, scheduler output containing private data, model
  transcripts, or generated release directories.

## Development Checks

The supported checks are listed in `tools/test/manifest.toml`:

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
python3 tools/test/runner.py source -- -q
npm run typecheck
npm run lint:public
npm run lint:skills
npm run test:package
```

Use the managed test environment selected by the test runner. Native Pi tests
require a prepared checkout matching `config/pi-source.json`; remote and live
model scenarios are opt-in. Stop any service started by a test and remove its
temporary state before the test process exits.

## Contract Changes

When changing a public capability, tool, workspace record, or protocol:

1. Update the versioned schema or catalog and its implementation.
2. Update the relevant English and Chinese documentation and Skill reference.
3. Add focused unit/contract tests and a recovery or failure-path test.
4. Run the package check so the release inventory remains complete.

Pull requests should explain compatibility impact, migration or rollback, and
which test lanes were run. Scientific claims belong in Findings with explicit
Artifact references; a successful process is not, by itself, scientific
evidence.

## Pull Requests

Use a descriptive title, include the problem and the bounded solution, and keep
unrelated formatting or generated files out of the diff. Maintainers may ask
for a smaller change when a proposal mixes runtime, scientific, and packaging
contracts.

See the [Maintainer Guide](docs/MAINTAINER_GUIDE.md) for release and ownership
details. Project-owned source is licensed under [Apache-2.0](LICENSE); check
third-party notices before redistributing a complete installation.
