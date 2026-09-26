# Pi Runtime Adapter

Pi is a transport and interaction host for TSPi. Python owns the deterministic
Research Kernel and compute services; Pi reads the canonical ResearchMap.

## Public Surface

The Root session uses:

```text
research_read         bounded ResearchMap and compute reads
research_change        one atomic ResearchMap ChangeSet
research_strategy     record or review a Claim strategy
research_interpretation interpret a completed Attempt
research_checkpoint    close the current Research Turn with a disposition
research_continuation  compatibility required-action ledger
system_prompt          inspect effective prompt provenance
compute_environment   local and remote compute environment catalog
compute_run          one bounded calculation lifecycle
execution_dispatch      pause or resume new work dispatch for one Node
analysis_run       registered local analysis
artifact_seed         Node-owned structure artifacts
artifact_import       Node-owned input artifacts
artifact_compare       deterministic structure comparison
artifact_render        registered visual artifact
report_build        revision-bound report package
review_run         advisory review
review_respond     Root disposition for a completed review

`notify_send` is a Host/Monitor-owned delivery capability and is not in the
Root Agent's default tool inventory.
```

Slash commands call the same command service: `/research`, `/compute`, `/runs`,
and `/debug prompt`. They are interaction syntax, not a second API.

## Root Session

The conversation is not scientific state. Before interpreting a previous turn,
read the current `ResearchMap`; after a write, use the returned revision or
`research_read mode=summary`. The research extension may include a bounded summary in
the prompt, but it cannot write the map. The Root Agent remains responsible for
method selection, interpretation, and stopping.

`research_read` modes are `map`, `summary`, `context`, `liveness`, `detail`, `locate`,
`validate`, `operations`, `decisions`, `evidence`, `storage`, `artifacts`,
`capabilities`, and `runs`. `capabilityKind=compute` lists
calculation capabilities; `capabilityKind=analysis` resolves analysis methods.
Use `kind` and `id` for a focused map object. Do not invent a second context
vocabulary for the ResearchMap.

## Isolation

Compute and Review child sessions receive bounded typed task packets and have no
authority to edit the ResearchMap. Compute action receipts, scheduler state,
and parser output are operational records. Review advice is advisory. Root
checks artifacts and applies any scientific interpretation with `research_change`.

The foreground UI and `/runs` browser are read-only presentations. TS Web reads
the canonical serialized `ResearchMap` directly; it does not rebuild a graph or
store a parallel snapshot.
