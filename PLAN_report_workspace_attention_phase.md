# Plan: report_workspace attention phase and claim readiness

## Problem

`report_workspace` currently mixes two responsibilities:

- summarize the workspace state for the model;
- route the model through hard-coded `allowed_next_actions` /
  `forbidden_next_actions` branches.

That forces the model to satisfy planner-shaped state fields instead of using
chemical judgment. It also creates brittle failures when a valid evidence record
does not match a narrow planner whitelist.

## Contract

Keep `current_phase`, but define it as an attention anchor:

- it names the scientific layer that most needs attention;
- it does not decide the next command or search method;
- it may be overridden by the model when the decision payload records a clear
  chemical rationale and `validate_decision` accepts the public command shape.

Move gate language to claim-readiness diagnostics:

- `claim_readiness.endpoint_minima`
- `claim_readiness.candidate`
- `claim_readiness.tsfreq`
- `claim_readiness.connectivity`
- `claim_readiness.accepted_ts`
- `claim_readiness.workspace`

Each readiness item reports `status`, supporting nodes, missing evidence, and
diagnostic notes. These diagnostics say which claims are supported or not
supported; they do not choose the next route.

## Public report shape

`report_workspace` should primarily expose:

- `current_phase`
- `current_phase_scope`
- `current_phase_reasons`
- `focus`
- `claim_readiness`
- `available_commands`: `start_node`, `end_node`, `ask_user`, `stop`
- `situation.context_items`
- `allowed_response_contract`

Compatibility fields may remain, but only as deprecated diagnostics:

- `blocking_gates` means missing evidence that blocks claim promotion.
- `allowed_next_actions` mirrors public command names only.
- `forbidden_next_actions` should not contain route-level planner classes.

## Enforcement boundary

`report_workspace` is read-only context.

`validate_decision`, `end_node`, accepted-audit validators, and evidence-gate
helpers enforce insufficient-evidence claim attempts. They are the right place
to reject malformed decisions or unsupported claim promotion.

## Implementation steps

1. Add a read-only claim-readiness builder in the plan-next layer.
2. Refactor phase inference to return attention phase and claim blockers, not
   route classes.
3. Update packet/public report payloads to expose claim readiness and available
   commands while demoting compatibility fields.
4. Prefer explicit `validation_gate` / `gate` metadata over evidence-kind
   whitelists and keep kind fallback for old records.
5. Scope Gaussian Opt MaxCycle parsing to the `Opt` route section so SCF
   `MaxCycle` does not pollute optimization diagnostics.
6. Update tests and docs so runtime behavior, skill instructions, and contract
   text describe the same responsibility split.
