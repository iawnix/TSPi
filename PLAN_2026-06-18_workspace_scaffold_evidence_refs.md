# Workspace Scaffold And Evidence Reference Repair Plan

- date: 2026年06月18日 22时45分
- scope: public workspace control-plane behavior; no chemistry execution changes

## Problem

`init_workspace` and the stored workspace contract drifted apart. The public
initializer creates the ledger files plus `nodes/` and `reports/`, while the
tree schema describes root-level `inputs/`, `accepted/`, and `rejected/` as
workspace directories. Runs that copy user reactant/product files into
`<workspace>/inputs/` therefore need an extra manual `mkdir`.

`start_node --evidence-ref` also accepts any string. A path-shaped value such as
`nodes/<node>/parsed/summary.json` can be written into `node.json` and
`tree.json`; the validator only reports the missing evidence id later. The
public command should either resolve a path to the unique registry evidence id
or fail before mutating the workspace.

## Design

1. Give root workspace directories one source of truth in the scaffold module.
   `init_workspace` and the older skeleton helper should both create
   `inputs/`, `nodes/`, `reports/`, `accepted/`, and `rejected/`.
2. Document that `init_workspace` pre-creates those root directories.
3. Add a reusable evidence-reference resolver at the `start_node` boundary:
   - known evidence ids pass through unchanged;
   - path-shaped refs are matched against `evidence_registry.json.records[].path`
     and normalized to the unique `evidence_id`;
   - unknown ids, unknown paths, and ambiguous paths fail with `SystemExit`
     before node artifacts or tree events are written.
4. Call the resolver in `start_node_from_cli_args()` before creating
   decision-card artifacts so `node.json.decision_provenance.evidence_refs` and
   `tree.json.events[].evidence_refs` store ids only. Keep a guard in the core
   start-node path for non-CLI callers.

## Validation

- Targeted tests:
  - `tests/test_workspace_primitives.py`
  - `tests/test_workspace_control_plane.py`
- Regression cases:
  - `init_workspace` creates all five root directories.
  - `start_node --evidence-ref <evidence_id>` succeeds.
  - `start_node --evidence-ref nodes/.../summary.json` succeeds and stores the
    matching evidence id in node provenance and tree events.
  - unknown evidence ids and unknown paths fail before mutation.
  - strict workspace validation remains clean after the success cases.
- Broader validation:
  - full `pytest -q`;
  - `compileall` with pycache redirected outside the skill tree;
  - sync installed runtime skill and repeat parity/tests before commit/push.
