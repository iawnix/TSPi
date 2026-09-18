# Scientific Capabilities: Usage and Operations

[English](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) | [简体中文](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)

This guide describes the current independent-analysis and Node-dispatch
contracts. It is an operational reference, not a historical acceptance report.

## Software and Dependencies

The managed runtime supplies Python, RDKit, ASE, NumPy, jsonschema, rendering
support, and the `ts-agent-kernel` wheel. Gaussian, xTB, CREST, and other native
programs remain administrator-managed backends. Discover supported capabilities
through the versioned catalog rather than assuming that a command is installed.

## Node Operations and Recovery

An analysis or dispatch belongs to one ResearchNode and writes only to its
Node-owned artifact area. `ts_manage` pause/resume operations create durable
operational receipts and do not change the scientific Node state. Inspection,
collection, parsing, and exact cancellation remain available while a Node is
paused. A restart must reconcile the latest receipt before another submission.

Use `ts_calc` for the common local/remote lifecycle:

```text
prepare -> submit -> inspect -> collect -> parse -> finalize
```

Remote completion is not proof that collection succeeded. Unknown submission or
cancellation outcomes must be inspected before retrying.

## Results, Reports, and Web

Analysis outputs live under `nodes/<node_id>/outputs/analysis/` and are bound to
input digests, generated files, and parser candidates. The Root Agent verifies a
candidate before promoting it through `ts_change` to an immutable Observation
or an explicit Finding. Reports and TS Web consume read-only projections; they
do not become a second scientific state store or choose the next Node.

Thermochemistry is limited to compatible HF/Kohn-Sham SCF energies, analytical
thermal corrections, and explicit RRHO models. Generic correlated-energy parsing,
isotope RRHO/KIE, conformer ensembles, and microkinetics are outside this
release. A missing or incompatible observation cannot be replaced by an
electronic energy.

## Verification Entry Points

Run focused tests while iterating and the release-backed source suite before
publishing:

```bash
python3 -m pytest -q tests/test_scientific_analysis.py tests/test_node_dispatch.py
python3 scripts/test_source.py -- -q
```

Remote smoke tests require an explicit `TS_REMOTE_CONFIG` and an administrator-
configured profile. They validate transport and parser integration only; a
small water or distorted-geometry job is not evidence for a chemical mechanism.
