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
are confined to the rendering target. No environment includes the CoRAgent wheel.

The public `install.sh` entry prepares these profiles using `manifest.json`.
A fresh installation without supplied `job.toml` selects `structure` locally;
existing bindings are preserved. Select other profiles explicitly:

```bash
./install.sh --source local --job-profile local:pyscf --job-profile local:render
./install.sh --job-config /absolute/job.toml --job-profile cluster:pyscf \
  --job-software-root cluster=/absolute/managed-science \
  --job-conda cluster=/absolute/conda/bin/conda
```

Configure the remote target, queue and native solver paths in `job.toml` first.
Remote paths belong to that target. Provisioning uses SSH and requires Python
3.11+, Conda, `timeout`, Linux x86_64 and the declared glibc; execution uses the
configured PBS/Torque scheduler and rsync. No controller Python path is copied
to the target. `wrapper` prepares Python for already configured Gaussian/xTB
backends; their native binaries remain operator-provided.

The installer stores pinned locks and immutable, versioned prefixes in a
dedicated owned directory (locally `~/soft/coragent/job-envs/<installation-id>`).
It writes their absolute bindings to `etc/job.toml`. PubChem/OPSIN service
settings live in `etc/name-resolver.toml`; local preparation can feed a remote
calculation without installing name services on every compute target.

Preparation and ordinary bounded acceptance Jobs complete before the current
release is switched or services stopped. The structure profile checks RDKit,
the resolver configuration path inside a Job, and ethanol geometry generation.
Optional profiles execute their declared minimal calculation/render. Reports
separate environment verification, tested backends, and unverified targets.
External name services are not contacted during this offline acceptance.
An existing remote target is only tested when selected for provisioning or with
`--verify-job-target cluster`.

For administrator maintenance, the lower-level target-local helper is still
available as `python3 scripts/install_job_environment.py --config /absolute/job.toml
--environment local --backend structure`. It requires existing explicit bindings
and does not perform the public installer's release activation or Job acceptance.
Structure and validation may share a prefix. CF22D needs no activation script
or `LD_PRELOAD` workaround.

Installation never solves dependencies again. Pinned pip artifacts download
to a cache below the environment parent and install with `--require-hashes`
and `--no-deps`; `pip check` verifies dependency completeness. The public
`--job-offline` flag uses only prepared caches; the lower-level helper's `--package-cache`
selects another artifact directory and `--offline` uses only that directory and
the Conda cache (`CONDA_PKGS_DIRS`). Locks and release files remain read-only.
An interrupted new prefix is removed; an existing prefix is never updated in
place. `--adopt` explicitly verifies a previously seeded environment against
the locks before publishing its receipt.

After configuring the bindings, run the installed control interpreter's
`-m research_agent.application.environment_check --config /absolute/job.toml`. This checks
the actual configured target and declared imports, including SSH targets.
Then execute a bounded scientific Job: matching package inventories and imports
alone do not prove a solver or method works.

For a lock refresh, solve the documented root requirements from conda-forge
in an isolated environment using `CONDA_OVERRIDE_ARCHSPEC=x86_64`, export
`conda list --explicit --sha256`, and validate a new installation plus actual
calculations before publishing the new lock. Fixed pip entries must include
the hashes of their upstream artifacts. Do not export credentials, add a
local-only wheel, or replace the lock of a running installation in place.
