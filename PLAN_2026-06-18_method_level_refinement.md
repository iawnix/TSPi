# Method, Level, And Refinement Selection Plan

- date: 2026年06月18日 00时58分
- scope: documentation contract only; no backend or planner behavior changes

## Problem

The current method-selection text mixes search strategies with potential
surfaces and execution backends. That makes xTB, Gaussian-External-xTB, and
semiempirical methods look like peers of scan, NEB, dimer, QST, and direct
TS optimization. They are not. They are levels/backends that can support
multiple search strategies.

The workflow also needs an explicit low-level to high-level refinement ladder:
low-level structures can generate candidates, but high-level refinement and
validation must prove the final claim.

## Design

1. Keep `references/backend_selection.md` as the linked file, but rewrite its
   contract around four orthogonal decisions:
   - workflow stage;
   - search strategy;
   - level/backend;
   - claim ceiling.
2. Add `references/refinement_ladder.md` for low-level-to-high-level candidate
   transfer, quality checks, drift handling, and validation gates.
3. Update `references/candidate_generation.md` so candidate routes are
   strategies first, then level/backend examples.
4. Update `references/gaussian_validation.md` so high-level TS/Freq validation
   is the refinement target for plausible candidates, not a default starting
   method.
5. Add reference-contract tests that prevent:
   - describing xTB or Gaussian-External-xTB as a search strategy peer of scan
     or NEB;
   - describing OptTS, QST2, or QST3 as default methods;
   - omitting the low-to-high refinement ladder from primary docs.

## Validation

- Targeted: `tests/test_reference_contract.py`.
- Broader docs/static: existing reference and import-boundary suites.
- Sync installed skill and rerun the same tests there before commit/push.
