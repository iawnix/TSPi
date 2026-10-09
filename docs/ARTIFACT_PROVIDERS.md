# Materials, provenance and read-only views

Artifact Store owns immutable payloads and provenance manifests. `artifact_register` imports a file, `artifact_create` stores new content, and `artifact_read` reads bounded content. Scientific execution uses `job_start`; `job_collect` registers actual outputs with their producing Job and inputs. Run analysis as a Job when it needs durable execution evidence.

A ResearchResult references registered materials in files, inputs or evidence_refs. Mutable Node work files are drafts until registered. Equal payload bytes do not identify a unique scientific producer, and browsing a material does not create a uses relation. Research conclusions remain Agent-authored interpretations of cited evidence.

The optional TS Web provider at `apps/agent-cli/research_web_bridge.py` exposes read-only Research Memory context, Node/Result details, relations and material references. It is a transport adapter, not an execution provider or alternate research database. Its versioned schema is under `contracts/ts-web/`.

See [execution boundaries](ARCHITECTURE_BOUNDARIES.md), [architecture and implementation status](ARCHITECTURE.md), and [historical decisions](archive/README.md).
