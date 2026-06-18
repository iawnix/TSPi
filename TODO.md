# TODO

## 2026-06-18 workspace control-plane refactor

Status: completed and merged to `main`.

### Scope

- Public workspace control is limited to six commands:
  `init_workspace`, `start_node`, `end_node`, `report_workspace`, and
  `validate_decision`, plus read-only `validate_workspace`.
- `node_disposition` is the public node state:
  `Running`, `Stopped`, `Error`, or `Success`.
- `phase` locates the workflow stage:
  `preflight`, `endpoint`, `rp_conformer_generation`,
  `candidate_generation`, `tsfreq_validation`, `connectivity_validation`, or
  `accepted_audit`.
- Program/runtime facts and mechanism interpretation are separated inside
  `closure_explanation`, not encoded as extra public state enums.
- Internal audit fields are derived for validators and the explorer, but old
  top-level node state fields are not persisted in `node.json`; they remain
  forbidden model-return fields in `report_workspace` and `validate_decision`.

### Validation To Keep Current

- `python scripts/ts_workspace.py --help` exposes only the six public
  commands.
- Removed workspace compatibility wrappers do not exist under `scripts/`.
- `pytest -q` passes in the authored checkout.
- Scratch workspace smoke covers `init_workspace`, `start_node`, `end_node`,
  `report_workspace`, `validate_decision`, strict workspace validation, and
  normalized explorer view.

### Completion Record

- Implementation commit: `e3baeae`.
- Merged to `main` and pushed to GitHub.
- Synced to `/home/iaw/.codex/skills/transition-state-workflow`.
- Validated authored checkout and installed skill tree with `257 passed, 2 skipped`.
- Deleted local and remote `refactor/ts-workspace-control-plane` branches.
- No matching workspace-control feedback remained in `/home/iaw/TS/.codex/TODO.md`.
