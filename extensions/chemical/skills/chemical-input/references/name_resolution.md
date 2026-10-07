# Name Resolution Contract

`chemical.name.resolve@1` is a deterministic analysis workflow. It accepts
the original name, an optional Agent-provided translated `lookup_name`, and may
validate explicitly supplied candidate SMILES. The
resolver must report its implementation and version; a model-generated
candidate is always marked `draft` until a deterministic resolver or an
explicit user confirmation establishes its identity.

The result distinguishes `resolved`, `ambiguous`, `draft`, and `unresolved`.
It includes canonical and isomeric SMILES, formula, formal charge, optional
InChI/InChIKey, unassigned stereocenters, and diagnostics. A missing resolver
backend is reported as an unsupported unresolved result. A reachable backend
that returns a deterministic not-found response is reported as an invalid
unresolved input. An absent Skill reference is a structured workflow
gap. A translated `lookup_name` is only a query hint; the resolver must validate
it and its provenance is retained alongside the original name. None of these
permits inventing a structure.

## Configuration

Automatic lookup uses the installation-owned configuration. Fresh package
installs copy `config/name-resolver.example.toml` into `etc/name-resolver.toml`;
operators may replace it or set
`TSPI_NAME_RESOLVER_CONFIG` to an absolute configuration path. The bundled
PubChem backend uses PUG REST, caches response evidence, and records the
endpoint, request URLs, response digests, implementation version, and fetch
time in `resolver_provenance`. OPSIN can be enabled as a second deterministic
HTTP backend. Network errors and multiple candidates remain unresolved or
ambiguous. No LLM-generated candidate is promoted by this configuration.

If neither `TSPI_NAME_RESOLVER_CONFIG` nor
`${TSPI_INSTALL_ROOT}/etc/name-resolver.toml` exists, no deterministic lookup
backend is available. When the workflow itself is registered,
`resolver=auto` still returns a normal `ts-analysis-result/1` with
`verdict="unsupported"`, `data.status="unresolved"`, no candidates, and
diagnostics explaining the missing backend. A `ts-workflow-gap/1` response
means the Skill reference is absent from the live analysis catalog. The
environment variable, when used, must name an absolute, readable regular
non-symlink file. The supported TOML shape is:

```toml
default_resolver = "auto"  # auto | pubchem | opsin

[backends.pubchem]
enabled = true
endpoint = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
timeout_seconds = 10  # 1..60
cache = true
# cache_dir = "/absolute/path/to/private/cache"
```

Only `pubchem` and `opsin` are valid configured backends. `llm` is an input
mode for explicitly supplied candidates and is never a deterministic backend.
Endpoints must be absolute HTTP(S) URLs; cache directories, when supplied,
must be absolute. A disabled or unavailable backend, a network failure, or
multiple candidates remains unresolved/ambiguous and must be surfaced in
provenance and diagnostics. An installed program directory or arbitrary
endpoint does not register a workflow.

Name lookup and structure identity are separate from 3D generation. After a
candidate is confirmed, call `artifact_create`, then validate the reaction and mapping
with the existing analysis capabilities.
