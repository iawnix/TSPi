# ADR 0010: Retire parallel runtime and State implementations

- Status: accepted
- Replaces: ADR 0007 and the capability-dispatch implementation in the independent scientific capabilities ADR
- Amends: the implementation details of ADR 0001 and ADR 0003

## Decision

Keep the production chain: installation launcher → Native Host/Pi Harness →
current Research State and Job Runtime. Remove obsolete implementations that
were retained only through their own exports, tests or release allowlists.

The removed code includes the old AppServer/composition/client facade, separate
session/context/memory stores and turn router, agent-pi-adapter, Compute/Review
protocols and aggregators, general JS/Python Provider execution, research-compute,
and the parallel typed State models. No compatibility facade replaces them.

ResearchMap concepts remain. The current `agent_workspace.py` mutation path,
shared operation contracts, invariants and `projection.py` own those records.
Removing old Python classes changes imports, not the canonical workspace format.

Preserve production consumers:

- Workspace validation, mode policy, workspace identity and Research State bridge.
- The Native Host activity journal and canonical ResearchMap reader.
- The HTTP adapter that connects to an existing Native Host.
- Operational ID allocation, now owned by `research_state.operational_ids` with
  the same durable counters and CLI operation.
- The TS Web `research-map-provider/1` JSONL adapter in `research_web_bridge.py`.
- Third-party extension provider inventory metadata; this is not a general
  execution dispatcher.

## Verification and release boundaries

Remove obsolete dedicated tests; preserve or move tests that exercise current
contracts, workspace initialization/recovery, execution identities and State
admission. Validate actual Native Worker, Host/HTTP, Web JSONL and installed-wheel
paths after the removal. Test count reduction reflects deleted implementations,
not relaxed acceptance rules.

The shared release inventory, npm package, Python wheel/bootstrap mappings and
architecture lint must agree. Retired runtime paths are rejected by source and
package checks so restoring an obsolete wildcard entry cannot silently ship them.

Existing workspaces, Job/evidence receipts and notification identities are not
rewritten. This cleanup performs no deployment or data migration. Historical
plans are labeled as historical; current architecture and Skills describe the
remaining executable paths.
