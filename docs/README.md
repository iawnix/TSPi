# CoRAgent Documentation

[English](README.md) | [简体中文](README.zh-CN.md)

Start with installation and terminal usage. This directory contains current user
and maintainer documentation. Superseded plans, migration inventories and one-off
validation reports are available in Git history.

| Need | Read |
| --- | --- |
| Skill catalog, loading language, and execution declarations | [Skills](../skills/README.md), [Execution catalog](EXTENSIONS.md) |
| Install, configure, upgrade and recover | [Installation and Operations](INSTALLATION.md) |
| Move an existing deployment to CoRAgent 0.19 | [Identity cutover](CORAGENT_CUTOVER.md) |
| Installation directories, state and managed environments | [Installation layout](APP_LAYOUT.md) |
| Workspace, Node, Result, Agent Server and Monitor ownership | [Architecture](ARCHITECTURE.md) |
| Research storage, tools and evidence | [Research Memory Skill](../skills/research-memory/SKILL.md), [Evidence architecture (Chinese)](RESEARCH_EVIDENCE_ARCHITECTURE.zh-CN.md) |
| Execution ownership and material provenance | [Execution boundaries](ARCHITECTURE_BOUNDARIES.md), [Artifact Store and views](ARTIFACT_PROVIDERS.md) |
| Scientific methods and execution | [Scientific operations](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) |
| Terminal, Phone and browser | [Terminal](TERMINAL.md), [CoRAgent Link](CORAGENT_LINK.md) |
| Maintain, test and package | [Maintainer Guide](MAINTAINER_GUIDE.md), [Contributing](../CONTRIBUTING.md) |
| Test environments, selection and cleanup | [Test runner](../tools/test/README.md) |
| Maintain the pinned Pi runtime | [Pi patches](PI_RUNTIME_PATCHES.md) |
| Coordinate the current mobile protocol cutover | [Phone protocol contract (Chinese)](CORAGENT_PHONE_PROTOCOL_MIGRATION.zh-CN.md) |
| Model/provider behavior | [Model Compatibility](MODEL_COMPATIBILITY.md) |

Current code and versioned schemas define behavior. Validation applies to the
tested source or release artifact; historical results do not certify a later
version. Project source uses [Apache License 2.0](../LICENSE); preserve separate
third-party dependency, Pi source and asset notices.
