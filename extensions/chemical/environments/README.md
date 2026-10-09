# Chemical execution environments

[简体中文](README.zh-CN.md)

These installation resources are separate from the Host control environment.
They are explicit Conda locks with SHA-256 package hashes, for Linux x86_64.
`wrapper.lock` requires glibc >=2.17; the scientific/rendering locks require
glibc >=2.28. CF22D uses a generic x86_64 PySCF build rather than the build
optimized for the maintainer's CPU. Other targets need their own verified lock.

| Lock | Bindings | Contents |
| --- | --- | --- |
| wrapper.lock | Gaussian/xTB Python wrappers | Python 3.11 and packaging tools; native solvers are installed separately |
| structure.lock | structure, validation | RDKit and NumPy |
| cf22d.lock | pyscf | PySCF, geomeTRIC and PySCF dispersion, all from Conda |
| render.lock + render.requirements.txt | render | RDKit, Cairo, Matplotlib, xyzrender and its rendering dependencies |

Text reports use the Host's standard library and do not need `render.lock`.
Rendering's notebook dependencies are upstream xyzrender requirements; they
are confined to the rendering target. No environment includes the TSPi wheel.

Copy the required lock files to a persistent directory on the target, keeping
`render.requirements.txt` beside `render.lock`. Configure absolute target paths
in installation-owned `job.toml`: `conda_executable`, a new versioned `prefix`
and `lock_ref`. The example at `config/compute.example.toml` uses editable
`/opt` paths. Local software can live under the operator's `~/soft` directory.

Run the installer on the target host (also for SSH targets):

```bash
python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend structure
python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend pyscf
python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend render
```

Choose either wrapper-backed solver's backend to install the common wrapper
prefix. Structure and validation may reference the same prefix and lock. The
CF22D lock needs no custom activation script or `LD_PRELOAD` workaround.

Installation never solves dependencies again. Pinned pip artifacts download
to a cache below the environment parent and install with `--require-hashes`
and `--no-deps`; `pip check` verifies dependency completeness. `--package-cache`
selects another artifact directory. `--offline` uses only that directory and
the Conda cache (`CONDA_PKGS_DIRS`). Locks and release files remain read-only.
An interrupted new prefix is removed; an existing prefix is never updated in
place. `--adopt` explicitly verifies a previously seeded environment against
the locks before publishing its receipt.

After configuring the bindings, run the installed control interpreter's
`-m tspi_runtime.environment_check --config /absolute/job.toml`. This checks
the actual configured target and declared imports, including SSH targets.
Then execute a bounded scientific Job: matching package inventories and imports
alone do not prove a solver or method works.

For a lock refresh, solve the documented root requirements from conda-forge
in an isolated environment using `CONDA_OVERRIDE_ARCHSPEC=x86_64`, export
`conda list --explicit --sha256`, and validate a new installation plus actual
calculations before publishing the new lock. Fixed pip entries must include
the hashes of their upstream artifacts. Do not export credentials, add a
local-only wheel, or replace the lock of a running installation in place.
