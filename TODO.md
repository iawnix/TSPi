# TODO

## 2026-06-18 workspace control-plane refactor

Status: implemented in the authored checkout; validate, commit, sync the
installed skill tree, and then clear the originating feedback in
`/home/iaw/TS/.codex/TODO.md`.

### Scope

- Public workspace control is limited to five commands:
  `init_workspace`, `start_node`, `end_node`, `report_workspace`, and
  `validate_decision`.
- `node_disposition` is the public node state:
  `Running`, `Stopped`, `Error`, or `Success`.
- `phase` locates the workflow stage:
  `preflight`, `endpoint`, `rp_conformer_generation`,
  `candidate_generation`, `tsfreq_validation`, `connectivity_validation`, or
  `accepted_audit`.
- Program/runtime facts and mechanism interpretation are separated inside
  `closure_explanation`, not encoded as extra public state enums.
- Internal audit fields remain available to validators and the explorer, but
  they are forbidden model-return fields in `report_workspace` and
  `validate_decision`.

### Validation To Keep Current

- `python scripts/ts_workspace.py --help` exposes only the five public
  commands.
- `python scripts/ts_hypothesis_workspace.py --help` reaches the same
  five-command entrypoint.
- `pytest -q` passes in the authored checkout.
- Scratch workspace smoke covers `init_workspace`, `start_node`, `end_node`,
  `report_workspace`, `validate_decision`, strict workspace validation, and
  normalized explorer view.

### Follow-Up

- After commit, sync to `/home/iaw/.codex/skills/transition-state-workflow`.
- Re-run the authored validation against the installed skill tree.
- Push the branch if this refactor is accepted for the GitHub-backed skill
  repository.
