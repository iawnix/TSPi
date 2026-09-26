# Capability And Compute Notes

[English](CAPABILITY_COMPUTE_MODEL.md) | [简体中文](CAPABILITY_COMPUTE_MODEL.zh-CN.md)

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
| named local/remote execution and Backend bindings | Compute Environment |
| remote transport and scheduler details | Platform |
| attempts, artifacts, scheduler receipts | workspace operational records |
| browser display | TS Web reading `ResearchMap.to_dict()` |

`FactFinding` and `IssueFinding` are the only scientific outputs recorded by a
Node. Parser output can be retained as an operational artifact until the Root
Agent verifies it and submits a `create_finding` operation. A Gate evaluation
is another map record and never implies a Claim status transition.

## Unified Compute

The installation owns one `.pi/compute.toml`. Its environment catalog contains
`kind = "local"` and `kind = "remote"` entries. Both expose the same public
operations, while a bounded child runtime performs the corresponding actions:

```text
launch   -> prepare, submit
inspect  -> status, optional tail
finalize -> collect, parse
cancel   -> cancel
```

Remote entries add Platform-owned SSH and scheduler fields. `/compute list`
and `/compute show <name>` query that catalog, so local and remote environments
share one public vocabulary.

The current chemistry adapters include `gaussian.scan@1` for Gaussian scan
energy profiles. `ase.neb@1` uses xTB by default and accepts the explicit
`calculator = "gaussian_cli"` parameter when each image must be evaluated with
Gaussian energies and Cartesian gradients. The selected calculator and its
route/resource settings are persisted in the run summary and checked during
parsing.

## Verification

Tests should cover capability input bounds, replay of source artifacts, digest
binding, and explicit ChangeSet promotion. No capability may change a Claim,
close a Node, or choose the next scientific question as a side effect.
