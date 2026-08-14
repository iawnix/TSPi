# Backend Selection

The Root Agent selects a backend and task. The Kernel only verifies that the
typed adapter can express the request and that its inputs satisfy the contract.

Use `ts_workspace_context mode=capabilities` to inspect static support. A
capability entry reports backend, task, required input roles, settings, and
expected artifacts. It does not prove that an executable, license, remote
profile, filesystem, queue, or scheduler is healthy.

Choose on scientific grounds:

- Gaussian can generate candidates and perform SP, optimization, frequency,
  combined optimization/frequency, and IRC work.
- xTB supports SP, optimization, frequency, combined optimization/frequency,
  scan, and MD within its typed contract.
- CREST supports conformer search.
- ASE supports NEB when its configured calculator contract is available.
- QBICS supports dMECP work through its typed adapter.

The catalog is not a priority list. Record the selected method and rationale in
the Root decision or Claim context, then let preparation generate operational
paths and manifests.
