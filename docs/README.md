# TSPi Documentation

[English](README.md) | [简体中文](README.zh-CN.md)

Use this page to choose the smallest document that answers a question. The
root [README](../README.md) is the installation overview; these documents are
the normative runtime and research contracts.

| Need | Read |
| --- | --- |
| Install, configure, upgrade, recover | [Installation and Operations](INSTALLATION.md) |
| Understand Agent, Kernel, Host, Monitor, Memory, and Compute boundaries | [Architecture](ARCHITECTURE.md) |
| Understand ResearchMap objects and turn checkpoints | [ResearchMap Design](RESEARCH_MAP_DESIGN.md) and [ADR 0006](adr/0006-unified-research-harness-lifecycle.md) |
| Select and run a registered scientific capability | [Capability and Compute Model](CAPABILITY_COMPUTE_MODEL.md) and [Scientific Capabilities Operations](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) |
| Use the terminal, Phone, browser, or Monitor | [Terminal](TERMINAL.md), [TSPi Link](TSPi_LINK.md) |
| Maintain, test, package, and release | [Maintainer Guide](MAINTAINER_GUIDE.md) and [Contributing](../CONTRIBUTING.md) |
| Understand model/provider support | [Model Compatibility](MODEL_COMPATIBILITY.md) |
| Review historical design decisions | [Architecture Decision Records](adr/) |

## Authority And Status

Code and versioned schemas are authoritative for behavior. Documentation
explains the public contract and must be updated with code changes. A historical
ADR is not an active compatibility promise; the current Native-only runtime and
the latest accepted ADRs define supported behavior.

The repository currently has no license grant. Do not redistribute or reuse the
source until the repository owner adds and confirms a license.
