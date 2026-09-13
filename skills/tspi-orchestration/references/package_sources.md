# Package Knowledge Sources

## Research Runtime

Use sources in this order:

1. registered public tool schemas for stable envelopes;
2. `ts_state` for live graph, artifacts, capabilities, and exact on-demand
   `ts_change` operation contracts;
3. `SKILL.md` for the research workflow;
4. one focused `references/*.md` file when its topic is active;
5. reusable files under `assets/` for Decision snippets or custom reports.

For a tool's accepted fields, query its live contract. The package-source reader
routes implementation lookups to the relevant public reference during research.

## Scientific Sources

Primary local program artifacts and explicit user-provided facts are source
material. Verify them before recording Observations. Use Review, activity logs,
scheduler history, reports, and conversations to locate the underlying evidence.

## Maintenance

Maintainers work in the authored Git checkout, where schemas and runtime code
define behavior. Update docs, templates, tests, and projections together with
the owning contract, then build and install a new release.
