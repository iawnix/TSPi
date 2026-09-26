# Pi Runtime Adapter

Pi is a transport and interaction host for TSPi. Python owns the deterministic
Research Kernel and compute services; Pi reads the canonical ResearchMap.

## Public Surface

The Root session uses:

```text
research.read         bounded ResearchMap and compute reads
research.change        one atomic ResearchMap ChangeSet
research.strategy     record or review a Claim strategy
research.interpretation interpret a completed Attempt
research.checkpoint    close the current Research Turn with a disposition
research.continuation  compatibility required-action ledger
system.prompt          inspect effective prompt provenance
compute.environment   local and remote compute environment catalog
compute.run          one bounded calculation lifecycle
execution.dispatch      pause or resume new work dispatch for one Node
analysis.run       registered local analysis
artifact.seed         Node-owned structure artifacts
artifact.import       Node-owned input artifacts
artifact.compare       deterministic structure comparison
artifact.render        registered visual artifact
report.build        revision-bound report package
review.run         advisory review
review.respond     Root disposition for a completed review

`notify.send` is a Host/Monitor-owned delivery capability and is not in the
Root Agent's default tool inventory.
```

Slash commands call the same command service: `/research`, `/compute`, `/runs`,
and `/debug prompt`. They are interaction syntax, not a second API.

## Root Session

The conversation is not scientific state. Before interpreting a previous turn,
read the current `ResearchMap`; after a write, use the returned revision or
`research.read mode=summary`. The research extension may include a bounded summary in
the prompt, but it cannot write the map. The Root Agent remains responsible for
method selection, interpretation, and stopping.

`research.read` modes are `map`, `summary`, `context`, `liveness`, `detail`, `locate`,
`validate`, `operations`, `decisions`, `evidence`, `storage`, `artifacts`,
`capabilities`, and `runs`. `capabilityKind=compute` lists
calculation capabilities; `capabilityKind=analysis` resolves analysis methods.
Use `kind` and `id` for a focused map object. Do not invent a second context
vocabulary for the ResearchMap.

## Isolation

Compute and Review child sessions receive bounded typed task packets and have no
authority to edit the ResearchMap. Compute action receipts, scheduler state,
and parser output are operational records. Review advice is advisory. Root
checks artifacts and applies any scientific interpretation with `research.change`.

The foreground UI and `/runs` browser are read-only presentations. TS Web reads
the canonical serialized `ResearchMap` directly; it does not rebuild a graph or
store a parallel snapshot.
