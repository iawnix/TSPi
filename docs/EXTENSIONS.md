# Installed Extension Contract

TSPi keeps the Agent and Research Kernel independent from installed scientific
software. An installed extension is a directory with a `manifest.json`; the
App Server discovers manifests listed in `TSPI_EXTENSION_MANIFESTS` (an OS
path-list), passed by its host configuration, or the optional package-owned
`extensions/manifest.json`.

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
    "tools": ["ts_amber"],
    "permissions": ["workspace.read"]
  }
}
```

Skill paths must contain a regular `SKILL.md`. Provider `kind` is one of
`compute`, `analysis`, or `harness`; a provider must declare a descriptor or
entry. Executable provider entries require a SHA-256 digest and are only
inventoried by the App Server loader. The loader does not import or execute
provider code. A trusted capability adapter can consume the inventory and
bind it to the environment manager.

For executable calculation providers, the trusted adapter registers a
`CapabilityDescriptor` through `register_capability_provider()`. Its
`prepare(task)` (or `prepare_task(task)`) method returns a bounded
`PreparedTask`; an optional `validate_inputs(workspace, intent, inputs)` method
owns provider-specific input checks. The adapter is the only component that
may translate a descriptor into a command. A descriptor without a registered
adapter is reported as an unavailable capability, rather than falling through
to a shell command or a backend-specific default.

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
keeping one default active tool set. `tspi-core-tools` owns research/lifecycle,
environment, review, dispatch, generic calculation, artifact import/render,
and report tools. `tspi-chemical-tools` owns chemical artifact seeding and
analysis (`artifact_seed`, `artifact_compare`, and `analysis_run`). Gaussian
and xTB are descriptor-only provider inventory entries in the default
`tspi-chemical` extension; their trusted Python adapters remain the execution
boundary and are selected through the environment manager.
