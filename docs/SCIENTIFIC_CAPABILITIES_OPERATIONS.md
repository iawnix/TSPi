# Scientific Capabilities: Usage and Operations

[English](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) | [简体中文](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)

This guide describes the current independent-analysis and Node-dispatch
contracts. It is an operational reference, not a second research protocol.

## Software And Dependencies

The managed runtime supplies Python, RDKit, ASE, NumPy, jsonschema, rendering
support, and the `ts-agent-kernel` wheel. Gaussian, xTB, CREST, and other
native programs remain administrator-managed Backends. Discover supported
capabilities through the versioned catalog rather than assuming a command is
installed.

## Node Operations And Recovery

An analysis or dispatch belongs to one ResearchNode and writes only to its
Node-owned artifact area. Pause/resume receipts are operational records and do
not change the scientific Node state. Inspection, collection, parsing, and
exact cancellation remain available while a Node is paused. A restart must
reconcile the latest receipt before another submission.

Use the same public `compute_run` operations for local and remote environments:

```text
launch   -> prepare, submit
inspect  -> status, optional tail
finalize -> collect, parse
cancel   -> cancel
```

The actions on the right are private child-runtime steps. Callers do not invoke
them as a second public lifecycle.

Remote completion is not proof that collection succeeded. Unknown submission or
cancellation outcomes must be inspected before retrying.

## Findings, Reports, And Web

Analysis outputs live under `nodes/<node_id>/outputs/analysis/` and are bound
to input digests, generated files, and transient parser candidates. The Root
Agent verifies a candidate before promoting it through `research_change` to a
`FactFinding` or `IssueFinding`. Reports and TS Web consume the canonical
`ResearchMap` serialization directly; they do not create a second scientific
state store or choose the next Node.

Thermochemistry is limited to compatible HF/Kohn-Sham SCF energies, analytical
thermal corrections, and explicit RRHO models. Generic correlated-energy
parsing, isotope RRHO/KIE, conformer ensembles, and microkinetics are outside
this release. Missing or incompatible evidence cannot be replaced by an
electronic energy.

## Verification Entry Points

Run focused tests while iterating and the release-backed source suite before
publishing:

```bash
python3 tools/test/runner.py fast -- -q
python3 tools/test/runner.py source -- -q
```

Remote smoke tests require an explicit `TS_COMPUTE_CONFIG` pointing to a
unified compute TOML with an administrator-configured remote environment. They
validate transport and parser integration only; a small molecule job is not
evidence for a chemical mechanism.
