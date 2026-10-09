---
name: gaussian
description: Prepare, run, and inspect Gaussian calculations, including single-point, optimization, frequency, transition-state, IRC, QST, and explicit scan inputs.
---

# Gaussian calculations

Use `chemical.gaussian@1` for XYZ `sp`, `opt`, or `opt-sp` calculations. Its
defaults are M062X/6-31G**, Opt=Tight or SP, SCF=Tight, and Int=UltraFine.
Use `chemical.gaussian-input@1` for a complete explicit Gaussian input.
Both use the target's `gaussian` binding.

```bash
"$TSPI_PYTHON" -m tspi_runtime.executors --config "$TS_JOB_CONFIG" --environment local --executor chemical.gaussian --version 1 --input geometry=input.xyz --output prepared/gaussian.json -- --task opt-sp --charge 0 --multiplicity 1
```

Submit the returned request file/digest with `job_start` and the intended Node.
Read the [runner contract](../method-selection/references/runner_results.md)
for shared output and electronic-state semantics. Check the route readback,
normal termination and convergence. An optimized structure without frequency
evidence is not a verified minimum.

## Explicit Gaussian inputs

Prepare a complete .gjf for TS/Freq/IRC/QST/scan. Each Link1 section must match
`--method`, `--basis`, `--threads`, `--memory-mb`, `--charge`, and `--multiplicity`.
For Geom=AllCheck, verify the checkpoint's electronic state. Stage dependencies
with `--dependency /absolute/source.chk=previous.chk`; input references must
be relative staged paths. Collect checkpoints needed by subsequent calculations.

```bash
"$TSPI_PYTHON" -m tspi_runtime.executors --config "$TS_JOB_CONFIG" --environment local --executor chemical.gaussian-input --version 1 --input input=ts.gjf --collect results/ts.chk --output prepared/ts.json -- --method M062X --basis '6-31G**' --charge 0 --multiplicity 1 --threads 12 --memory-mb 4000 --validation saddle
```

`--validation opt/sp/frequency/minimum/saddle/irc/none` selects runner checks.
`saddle` requires stationary-point convergence and one imaginary frequency;
inspect its mode direction and use the registered saddle validator for the
specified transformation. IRC produces path and endpoint artifacts; establish
endpoint identities with the connectivity validator and supporting evidence.
A scan input can execute, but scan-specific completeness has no bundled validator.

See [Gaussian scientific validation](references/gaussian_validation.md).
