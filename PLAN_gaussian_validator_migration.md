# Gaussian Validator Migration Plan

## Goal

Retire `gaussian-ts-validator` as an independent implementation by moving its
remaining concrete Gaussian utilities into `transition-state-workflow` while
preserving the current workflow boundaries.

## Boundaries

- `ts_backends.gaussian` owns Gaussian input construction and Gaussian log
  parsing. It may create node-scoped input or parsed artifact files, but it must
  not mutate workspace ledgers or set node verdicts.
- `ts_remote` owns remote staging, execution, and artifact fetching. It must not
  parse chemistry or write scientific verdicts.
- `mol_comparator` remains the structure-comparison layer. No Gaussian process
  or TS/Freq parser logic should enter this module.
- `gaussian-ts-validator` becomes a thin transitional entrypoint only.

## Migration Steps

1. Move XYZ frame selection, Gaussian route normalization, GJF writing, Gen/ECP
   section handling, Gaussian section selection, strict TS/Freq parsing, and
   final-geometry extraction into `ts_backends.gaussian`.
2. Add thin script wrappers in `scripts/` for the migrated Gaussian prepare and
   parse commands so existing operator workflows have stable entrypoints.
3. Add a Gaussian remote adapter under `ts_remote` without exposing a standalone
   `run_remote_gaussian.py` script. The adapter must disable `set -u` while
   sourcing `g16.profile` or initialize `LD_LIBRARY64_PATH` before source.
4. Port the `gaussian-ts-validator` regression tests to
   `transition-state-workflow` and keep assertions focused on the migrated
   public functions/CLI behavior.
5. Update references and `SKILL.md` so Gaussian validation points to the new
   backend/remote owners.
6. Sync the installed skill tree, validate authored and installed copies, commit
   and push, then mark the `/home/iaw/TS/.codex/TODO.md` Gaussian runner item as
   resolved.

## Acceptance Checks

- Authored checkout targeted Gaussian tests pass.
- Authored checkout full tests pass.
- Authored checkout compiles without syntax errors.
- Installed skill is directory-equivalent to authored checkout, excluding git
  and cache artifacts.
- Installed skill targeted/full tests pass.
- `gaussian-ts-validator/SKILL.md` no longer claims it owns runnable logic beyond
  transitional routing, and no transitional `run_remote_gaussian.py` script
  remains.
