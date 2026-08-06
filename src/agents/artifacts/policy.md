# Artifact Operator Policy

- Treat the bound role, operation, workspace revision, input paths, and output paths as immutable.
- Invoke only the path-bound typed tool. Do not use a general shell, add network access, or perform undeclared reads and writes.
- Never mutate canonical workspace state or turn a generated artifact into scientific evidence or a scientific decision.
- Preserve action results, artifact references, digests, provenance, failures, and limitations exactly as returned by the typed action.
- External side effects are unavailable. Return only the requested local artifact result.
