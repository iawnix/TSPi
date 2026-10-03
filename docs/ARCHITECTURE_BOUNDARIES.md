# Compute and Memory boundaries

`research-compute` is a domain neutral execution lifecycle. It owns input
binding, Attempt records, scheduling, local/remote receipts, output digest
checks and provenance. It defines the `ComputeProvider` protocol and a
process-local registry; it never imports a scientific implementation.

Chemistry is an extension. `extensions/chemical` registers one provider for
Gaussian, xTB, CREST, ASE/NEB and PySCF. The provider owns task preparation,
program parsers, structure operations and analysis algorithms. Application
bootstrap performs registration. If the extension is not installed, Compute
returns `capability_provider_unavailable` instead of loading a fallback.

There are two memory scopes:

* `research-memory` owns the durable, rebuildable workspace projection at
  `memory/index.json`. It reads committed Research State and writes a
  projection through `ProjectionWriter`; it cannot apply a State change.
* Agent Core owns only the current process's session memory. Its
  `agent_session` memory port has no workspace filesystem and cannot be used
  as scientific memory. The Host may add the read-only Research Memory context
  as `kernel_context` when building a bounded Agent context.

Research State remains the sole authority for ResearchMap, revision,
lifecycle and provenance. State commits invoke only the projection protocol;
the concrete writer is installed by the application layer.
