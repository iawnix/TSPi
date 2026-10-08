# Artifact execution and evidence

The former ArtifactProvider registry and general Provider dispatcher have been
removed. Scientific execution uses installed Skill scripts through `job_start`;
`job_collect` registers actual outputs with producer and input provenance.

`artifact_register` preserves existing material, `artifact_create` preserves new
content, and `artifact_link` records evidence relations. `artifact_derive` records
a derivation descriptor only; it does not execute an analyzer or create its output.
Run real analysis as a Job and register the output before using it as evidence.

Installed extension validators are invoked through Job Runtime and produce bound
result receipts. Registered acceptance profiles declare finite checks. They do
not select methods or implement a second workflow engine.

Extension `providers` metadata remains readable for third-party inventory; it
does not grant a general provider execution API. The TS Web provider is a separate
read-only ResearchMap JSONL adapter at `apps/agent-cli/research_web_bridge.py`, using
`research-map-provider/1`; it does not load arbitrary Python entry points.

See [execution boundaries](ARCHITECTURE_BOUNDARIES.md),
[the architecture](ARCHITECTURE.md), and [the retirement decision](adr/0010-retire-parallel-runtimes.md).
