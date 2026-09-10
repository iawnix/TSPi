# Program Runtime Failures

Keep failure domains separate before deciding scientific meaning.

## Triage Order

1. Confirm the immutable intent, Node, backend, input artifact digests, and
   execution target.
2. Inspect durable control guards and receipts before any resubmit/cancel.
3. Distinguish SSH/transfer, scheduler, remote bootstrap, software activation,
   scratch, program, output, parser, and collection failure.
4. Collect all declared outputs that exist and verify them locally.
5. Record scientifically meaningful negative or anomalous observations only
   when primary artifacts support them.
6. Decide retry, recalculation, changed strategy, new Node, user escalation, or
   stop as the Root Agent.

## Common Classes

- **Pre-effect failure**: validation, local preparation, or upload failed before
  scheduler submission. Retry may be safe only when the typed result says so.
- **Ambiguous external effect**: the request may have reached the scheduler but
  no authoritative result returned. Reconcile; never blind-replay.
- **Remote bootstrap failure**: activation, scratch, or wrapper failed before
  the scientific program created its main output.
- **Input failure**: the program reports route, keyword, coordinate, charge,
  spin, or control-file syntax error.
- **Program convergence/electronic failure**: the program ran but SCF,
  optimization, frequency, IRC, state, or numerical work failed.
- **Parser failure**: a valid or failed primary output exists but the local
  parser cannot express it. Preserve both artifact and parser error.

## Retry Versus New Work

Retry only an unchanged intent with proven retry safety. Recalculation preserves
the source Node/intent and states changed parameters and purpose. Start a new Node
when the scientific objective, hypothesis, method rationale, or branch changes.

Program failure is normally an operational fact. It contradicts a Claim only
when a frozen ProofSpec deliberately treats the verified observation as a
scientific failure condition.

Record durable summaries through the existing calculation record, Finding, and
Node result. Do not invent an Observation merely to make an operational error
visible.
