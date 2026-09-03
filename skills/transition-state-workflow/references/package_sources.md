# Package Knowledge Sources

## Research Runtime

Use sources in this order:

1. registered public tool schemas for exact call fields;
2. `ts_state` for live graph, artifacts, and capability catalogs;
3. `SKILL.md` for high-frequency policy;
4. one focused `references/*.md` file when its topic is active;
5. reusable files under `assets/` for Decision snippets or custom reports.

Do not inspect package implementation or tests to guess a public call during an
ordinary study. The package-source guard redirects such reads to the maintained
public contract. It is a routing guard, not a general filesystem sandbox.

## Scientific Sources

Primary local program artifacts and explicit user-provided facts are source
material. Verify them before recording Observations. Review, tool prose,
activity entries, scheduler history, reports, and old conversations are not
scientific source records by themselves.

## Maintenance

Maintainers work in the authored Git checkout, where schemas and runtime code
are authoritative. Update docs, templates, tests, and projections together with
the owning contract. Installed releases are immutable and must not be edited.

The release intentionally excludes tests and build scripts. Their absence in an
installation is expected and must not cause Root runtime source hunting.
