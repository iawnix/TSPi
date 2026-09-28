# Name Resolution Contract

`chemical.name.resolve@1` is a deterministic analysis capability. It accepts
the original name and may validate explicitly supplied candidate SMILES. The
resolver must report its implementation and version; a model-generated
candidate is always marked `draft` until a deterministic resolver or an
explicit user confirmation establishes its identity.

The result distinguishes `resolved`, `ambiguous`, `draft`, and `unresolved`.
It includes canonical and isomeric SMILES, formula, formal charge, optional
InChI/InChIKey, unassigned stereocenters, and diagnostics. A missing resolver
is a structured capability gap, not permission to invent a structure.

## Configuration

Automatic lookup is opt-in. Copy `config/name-resolver.example.toml` from the
package into the installation-owned `.pi/name-resolver.toml`, or set
`TSPI_NAME_RESOLVER_CONFIG` to an absolute configuration path. The bundled
PubChem backend uses PUG REST, caches response evidence, and records the
endpoint, request URLs, response digests, implementation version, and fetch
time in `resolver_provenance`. OPSIN can be enabled as a second deterministic
HTTP backend. Network errors and multiple candidates remain unresolved or
ambiguous. No LLM-generated candidate is promoted by this configuration.

Name lookup and structure identity are separate from 3D generation. After a
candidate is confirmed, call `artifact_seed`, then validate the reaction and mapping
with the existing analysis capabilities.
