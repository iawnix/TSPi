# ADR 0007: Research Agent Framework Boundaries

Status: superseded by [ADR 0010](0010-retire-parallel-runtimes.md).

This historical design used a parallel framework and/or capability dispatch path
that is no longer implemented. Its implementation and isolated tests have been
removed. The accepted current boundaries are described in [ARCHITECTURE.md](../ARCHITECTURE.md)
and [execution boundaries](../ARCHITECTURE_BOUNDARIES.md).

Use the Native Host/Pi Harness, current Research State, Job Runtime and installed
Skills. `artifact_derive` records a descriptor; it does not execute a provider.
The original decision and implementation remain available in Git history.
