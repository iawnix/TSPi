# Changelog

This file records user-visible changes. Current architecture is documented in
[the architecture guide](docs/ARCHITECTURE.md); earlier designs remain in Git history.

## Unreleased

- **0.19.0 breaking rename:** the product and repository are CoRAgent / `coragent`.
  Commands, package identities, services, installation metadata and environment
  variables use `coragent` / `CORAGENT_`; no legacy aliases or fallback readers.
  The internal Python import namespace remains `research_agent`.
- Host/Relay use `coragent-host/2`, `coragent-link.v1`, `cah_` and `cad_`.
  Deploy the matching CoRHub client and pair again; old tokens cannot be renamed.
  Existing installations require the [explicit cutover](docs/CORAGENT_CUTOVER.md).

- Updated the pinned Pi runtime and SDK packages to 1.1.0, retaining protocol 8
  and request admission with the new context API and token estimator.
- Research tool cards display recorded execution time, including after reconnect;
  Job submission time remains distinct from the background computation duration.
- Added Gaussian relaxed-scan capability documentation and Gaussian-backed ASE
  NEB support.
- Removed the retired ordinary-Pi runtime from the supported package surface;
  Native Pi Harness is the only runtime entrypoint.
- Clarified the Research Memory, bounded turn context, capability catalog, and
  Monitor wake-up boundaries.
- Added repository governance documents and automated Skill contract checks.
- Added the Apache-2.0 license and SPDX metadata for project-owned source.

There is no published release tag for this entry yet. Release notes must include
the package version, pinned Pi revision, migration notes, and the test lanes run.
