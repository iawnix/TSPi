# Pi Runtime Adapter

Pi is a transport and interaction host for TSPi. Python owns the deterministic
Research Kernel and compute services; Pi does not maintain a second state model.

## Public Surface

The Root session uses:

```text
ts_state         bounded ResearchMap and compute reads
ts_change        one atomic ResearchMap ChangeSet
ts_environment   local and remote compute environment catalog
ts_calc          one bounded calculation lifecycle
ts_dispatch      pause or resume new work dispatch for one Node
ts_analyze       registered local analysis
ts_seed/import   Node-owned structure and input artifacts
ts_compare       deterministic structure comparison
ts_render        registered visual artifact
ts_report        revision-bound report package
ts_review/reply  advisory review and Root disposition
ts_notify        configured delivery events
```

Slash commands call the same command service: `/research`, `/compute`, `/runs`,
and `/debug prompt`. They are interaction syntax, not a second API.

## Root Session

The conversation is not scientific state. Before interpreting a previous turn,
read the current `ResearchMap`; after a write, use the returned revision or
`ts_state mode=summary`. The research extension may include a bounded summary in
the prompt, but it cannot write the map. The Root Agent remains responsible for
method selection, interpretation, and stopping.

`ts_state` modes are `map`, `summary`, `detail`, `locate`, `operations`,
`artifacts`, `capabilities`, and `runs`. `capabilityKind=compute` lists
calculation capabilities; `capabilityKind=analysis` resolves analysis methods.
Use `kind` and `id` for a focused map object. Do not invent a second context
vocabulary for the ResearchMap.

## Isolation

Compute and Review child sessions receive bounded typed task packets and have no
authority to edit the ResearchMap. Compute action receipts, scheduler state,
and parser output are operational records. Review advice is advisory. Root
checks artifacts and applies any scientific interpretation with `ts_change`.

The foreground UI and `/runs` browser are read-only presentations. TS Web reads
the canonical serialized `ResearchMap` directly; it does not rebuild a graph or
store a parallel snapshot.
