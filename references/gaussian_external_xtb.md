# Gaussian External xTB Backend

Use this reference when Gaussian is the driver and xTB supplies the external
energy, gradient, and Hessian through Gaussian's EIn/EOu External protocol.
For method evidence limits, read `references/mechanism_analysis_sources.md`.

This is the opposite direction from the ASE NEB external-Gaussian calculator:
there, ASE drives a path and Gaussian supplies forces. Here, Gaussian drives an
optimization or frequency-style request and xTB supplies the numerical
quantities that Gaussian reads back.

## Claim Boundary

Gaussian-External-xTB is a low-level execution backend. It may support
candidate generation, low-cost optimizer trials, and screening-level reaction
center evidence. It must not write `claim_status=accepted_ts`, and it is not a
replacement for Gaussian DFT TS/Freq plus connectivity validation.

If the result looks chemically promising, branch to a Gaussian DFT validation
node and then run displacement/connectivity or IRC checks as needed.

## Protocol

Gaussian calls the wrapper with six positional arguments:

```text
<layer> <EIn> <EOu> <MsgFile> <FChkFile> <MatElFile>
```

The EIn header is:

```text
natoms derivative-level charge multiplicity
```

Derivative levels are:

- `0`: energy only.
- `1`: energy plus gradient.
- `2`: energy plus gradient plus Hessian.

Atom lines are in Bohr:

```text
atomic-number x y z MM-charge
```

The backend writes xTB input coordinates in Angstrom. xTB energy, gradient, and
Hessian artifacts are read as Hartree, Hartree/Bohr, and Hartree/Bohr^2,
matching Gaussian EOu units.

Embedded MM charges or point-charge tail blocks are detected and rejected in
this backend version. Do not allow those charges to be silently ignored.

## xTB Mapping

The wrapper reuses the shared xTB backend mapping:

- charge -> `--chrg`;
- multiplicity -> `--uhf` as unpaired electrons, equal to multiplicity minus
  one;
- derivative level `1` -> `--grad`;
- derivative level `2` -> `--hess`.

Missing Hessian output for a Hessian request is a hard failure. The wrapper must
not substitute zeros or downgrade the request.

Explicit branch variables include xTB method, accuracy, electronic temperature,
iteration cap, solvent, solvent model, executable path, and thread count. xTB
threads are passed through `OMP_NUM_THREADS`.

## Gaussian Route Shape

Keep Gaussian and xTB responsibilities clear. Gaussian is the optimizer/freq
driver; xTB is the external energy/derivative provider.

Example route fragment:

```text
#P External="python scripts/gaussian_external_xtb.py --workdir nodes/n120_gaussian_external_xtb/outputs --method gfn2 --accuracy 0.2 --parallel 24" NoMicro
```

For transition-state trials, prefer separate Opt and Freq-style jobs unless the
exact Gaussian/xTB combination has already been tested for this system. Use
`NoMicro` with External routes to avoid Gaussian microiteration behavior that
does not match the xTB external provider.

For heavy elements, Gaussian may still need a broad dummy basis declaration so
its parser accepts the element list, even though xTB supplies the energy and
derivatives.

## Node Scope And Artifacts

Run from `nodes/<node_id>/outputs`, not the workspace root. The backend writes
or preserves:

- the Gaussian EIn request and EOu reply;
- `gaussian_external_xtb_input.xyz`;
- xTB stdout/stderr captures;
- fixed-name xTB artifacts such as `gradient`, `hessian`, and `energy`;
- `gaussian_external_xtb_summary.json`.

The summary is backend evidence only. It records `candidate_only=true` and
`accepted_ts_capable=false`; workflow state is still owned by the normal node
finalization tools.
