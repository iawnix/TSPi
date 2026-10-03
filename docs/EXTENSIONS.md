# Installed Extension Contract

TSPi keeps the Agent and Research State independent from installed scientific
software. An installed extension is a directory with a `manifest.json`; the
App Server discovers manifests listed in `TSPI_EXTENSION_MANIFESTS` (an OS
path-list), passed by its host configuration, or every package-owned
`extensions/*/manifest.json` file.

The manifest format is `tspi-extension/1`; its JSON Schema is
`contracts/tspi-extension/1/extension-manifest.schema.json`:

```json
{
  "schema_version": "tspi-extension/1",
  "name": "amber-tools",
  "version": "1.2.0",
  "skills": [{"name": "amber", "path": "skills/amber"}],
  "providers": [{
    "id": "amber.md",
    "version": "1",
    "kind": "compute",
    "descriptor": "providers/amber.json",
    "entry": "providers/amber.mjs",
    "sha256": "sha256:<64 hex characters>"
  }],
  "server": {
    "entry": "server/index.mjs",
    "sha256": "sha256:<64 hex characters>",
    "tools": ["amber_run"],
    "permissions": ["workspace.read"]
  }
}
```

Skill paths must contain a regular `SKILL.md`. Extension provider entries are
metadata only; compute descriptors are resolved by the Python Native registry.
The App Server loader inventories extension metadata but never imports a
JavaScript compute provider. Native preflight owns input checks, command
bindings, intent materialization, execution, and parsing. A missing Native
capability is reported as unavailable rather than falling through to a shell
command or backend default.

The existing `extensions/server/extensions.json` contract remains unchanged:
server tools still require a package-owned manifest, allowlist selection, and
per-entry digest. Installed manifests add Skills, provider metadata, and
explicitly allowlisted server tools without changing Agent core, Harness
lifecycle, or the built-in server tools.

An empty or unset `TSPI_EXTENSION_MANIFESTS` value is valid and leaves the
package's built-in Skills and capabilities unchanged. Duplicate extension,
provider, or Skill names, path traversal, symbolic links, malformed metadata,
and digest mismatches fail closed before a session starts.

The optional `server` entry is executable only when its extension name is in
the Host allowlist `TSPI_INSTALLED_SERVER_EXTENSIONS`. Its module must export
`createServerExtension()`, and returned Harness tools must exactly match the
declared names, parameter schemas, and lifecycle metadata. The entry digest is
checked during discovery and immediately before import; the Agent cannot
choose an import path or bypass the allowlist.

The package-owned server inventory is split into two signed entries while
keeping one default active tool set. `core-tools` owns research/lifecycle,
environment, review, dispatch, generic calculation, artifact import/render,
and report tools. `chemical-tools` owns chemical artifact seeding and
analysis (`artifact_seed`, `artifact_compare`, and `analysis_run`). Gaussian
and xTB are descriptor-only metadata entries in the default `chemical`
extension; the Python Native registry is the only execution boundary.
