# Installed Extension Contract

Here `extensions/` means installable capability extensions. Package-owned core
server tool assembly lives under `apps/app-server/server-tools/` and is outside
the installed-extension discovery flow.

ResearchAgent keeps the Agent and Research Memory independent from installed scientific
software. An installed extension is a directory with a `manifest.json`; the
App Server discovers manifests listed in `RESEARCH_AGENT_EXTENSION_MANIFESTS` (an OS
path-list), passed by its host configuration, or every package-owned
`extensions/*/manifest.json` file.

The manifest format is `research-agent-extension/1`; its JSON Schema is
`contracts/research-agent-extension/1/extension-manifest.schema.json`:

```json
{
  "schema_version": "research-agent-extension/1",
  "name": "amber-tools",
  "version": "1.2.0",
  "skills": [{"name": "amber", "path": "skills/amber"}],
  "server": {
    "entry": "server/index.mjs",
    "sha256": "sha256:<64 hex characters>",
    "tools": ["amber_run"],
    "permissions": ["workspace.read"]
  }
}
```

Skill paths must contain a regular `SKILL.md`. Extension provider entries are
legacy metadata for optional server integrations; scientific Skills do not need
provider descriptors. The App Server loader inventories extension metadata.
Scientific preflight checks the selected Job Runtime environment, while the
Skill owns input construction, command argv, parsing, and validation. A
scientific command is submitted through `job_start`, which is the shared local
and remote execution boundary.

The existing `apps/agent/tools/legacy-extensions.json` contract remains unchanged:
server tools still require a package-owned manifest, allowlist selection, and
per-entry digest. Installed manifests add Skills, provider metadata, and
explicitly allowlisted server tools without changing Agent core, Harness
lifecycle, or the built-in server tools.

An empty or unset `RESEARCH_AGENT_EXTENSION_MANIFESTS` value is valid and leaves the
package's built-in Skills and capabilities unchanged. Duplicate extension,
provider, or Skill names, path traversal, symbolic links, malformed metadata,
and digest mismatches fail closed before a session starts.

The optional `server` entry is executable only when its extension name is in
the Host allowlist `RESEARCH_AGENT_INSTALLED_SERVER_EXTENSIONS`. Its module must export
`createServerExtension()`, and returned Harness tools must exactly match the
declared names, parameter schemas, and lifecycle metadata. The entry digest is
checked during discovery and immediately before import; the Agent cannot
choose an import path or bypass the allowlist.


The active bundled server entry is core-tools: Research Memory, generic Job Runtime and Artifact tools. Chemical and email extensions supply Skills with scripts; no chemical-tools or native notification entry is loaded. providers is optional legacy metadata. An executable Skill declares resources_sha256 for its resources.json index, whose paths are relative to the extension root. The loader validates the index and every listed script/helper digest. Regenerate hashes with scripts/update_skill_resources.py after changing Skill resources.
