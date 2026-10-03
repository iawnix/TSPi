# Artifact Providers

Skills describe scientific intent and decision rules. They do not install
executables, write workspace artifacts, or grant command execution. An
extension owns those operations through an `ArtifactProvider`.

An artifact provider publishes one or more `ArtifactOperationDescriptor`
values. Each descriptor declares:

- input and parameter JSON Schemas;
- the provider-owned result JSON Schema;
- output roles and a provenance schema identifier;
- the operation version and declared effects.

The Research State runtime discovers providers through
`research_compute.artifact_registry.register_artifact_provider`. It exposes
the descriptors in a catalog, validates the result envelope, and checks that
the result provenance names the registered provider and descriptor digest.
Provider objects and command paths are never returned by the catalog.
Call `validate_artifact_request` before `prepare` to apply the provider-owned
input and parameter schemas.
Use `artifact_operation_digest(descriptor)` when producing the provenance
digest; this binds a result to the exact published schemas and version.

The adapter boundary is intentionally small:

```python
class MyProvider:
    provider_id = "my-tool"

    def operations(self):
        return [descriptor]

    def prepare(self, operation, request, context):
        ...

    def execute(self, prepared, context):
        return {
            "operation": descriptor.operation,
            "version": descriptor.version,
            "result": {"...": "provider-owned data"},
            "provenance": {
                "provider_id": self.provider_id,
                "descriptor_digest": "sha256:...",
                "inputs": [{"artifact_id": "...", "sha256": "..."}],
                "outputs": [{"artifact_id": "...", "sha256": "..."}],
            },
        }
```

The generic contract does not move existing chemical handlers. Gaussian,
xTB, structure generation, and analysis can adopt it incrementally. Until an
extension registers an adapter, a Skill can only describe a capability and the
Research State runtime must report a capability gap; it must not infer an executable command.
