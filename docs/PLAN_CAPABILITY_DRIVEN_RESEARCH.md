# Capability And Compute Notes

[English](PLAN_CAPABILITY_DRIVEN_RESEARCH.md) | [简体中文](PLAN_CAPABILITY_DRIVEN_RESEARCH.zh-CN.md)

Capabilities are execution descriptions, not research state. A capability
declares bounded inputs, outputs, versions, and deterministic failure behavior.
The Root Agent chooses when to invoke one for a ResearchNode; the kernel does
not route to a successor node.

## Ownership

| Concern | Owner |
| --- | --- |
| phases, claims, nodes, findings, gates | `ResearchMap` and `ResearchKernel` |
| procedure and capability guidance | Skills |
| software invocation and parsing | Backends |
| local/container/HPC placement | Compute `Platform` profiles |
| attempts, artifacts, scheduler receipts | workspace operational records |
| browser display | TS Web reading `ResearchMap.to_dict()` |

`FactFinding` and `IssueFinding` are the only scientific outputs recorded by a
Node. Parser output can be retained as an operational artifact until the Root
Agent verifies it and submits a `create_finding` operation. A Gate evaluation
is another map record and never implies a Claim status transition.

## Unified Compute

The installation owns one `.pi/compute.toml`. Its profile catalog contains
`kind = "local"` and `kind = "remote"` entries. Both use the same
`prepare -> submit -> inspect -> collect -> parse` lifecycle; remote entries
add SSH and scheduler fields. `/compute list` and `/compute show <name>` query
that catalog, so local and remote environments share one public vocabulary.

## Verification

Tests should cover capability input bounds, replay of source artifacts, digest
binding, and explicit ChangeSet promotion. No capability may change a Claim,
close a Node, or choose the next scientific question as a side effect.
