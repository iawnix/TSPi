# Compute Hosts

Use this for known host-specific details. Re-check live before making current claims.

## compute-0-30

Validated names:

- login host from local SSH config: `iaw.1w`
- compute host from login node: `compute-0-30`
- host output: `compute-0-30.local`

Gaussian:

- executable: `/home/iaw/soft/Gaussian/g16/g16`
- profile: `/home/iaw/soft/Gaussian/g16/bsd/g16.profile`
- source the profile with relaxed strictness because it can reference unset variables.

xTB/ASE Python:

- xTB: `/home/iaw/soft/xtb/6.7.1/bin/xtb`
- Python env: `/home/iaw/soft/conda/envs/AresTSTools_Computer_30/bin/python`
- sanitize `LD_LIBRARY_PATH` before ASE/SciPy work; GCC 11.3.0 libraries can require `GLIBC_2.18` and break imports.
- Keep remote-imported helpers compatible with older compute-host Python
  versions. Function annotations may stay modern under
  `from __future__ import annotations`, but runtime-evaluated aliases must not
  use PEP 585 builtins such as `Alias = tuple[...]`; use `typing.Tuple` /
  `typing.List` for those aliases instead.
- Do not assume the full control-plane package should run inside this older
  ASE/xTB environment. Prefer a small engine wrapper or a documented
  py38-compatible remote subset for ASE/xTB execution, while the local
  workflow controller, validator, and web explorer may use the maintained
  package baseline. Before submitting long ASE/xTB jobs, run the py38
  compatibility gate for the remote-imported subset or a direct
  `python -m py_compile` smoke in the target environment.
- The ASE NEB CLI parser must tolerate Python 3.8: do not require
  `argparse.BooleanOptionalAction`, and avoid py310-only APIs such as
  `zip(..., strict=True)` in the remote ASE/xTB path.

QBICS:

- gcc: `/home/iaw/soft/gcc/8.1.0_glibc2.17`
- OpenMPI: `/home/iaw/soft/Openmpi/4.1.6`
- QBICS: `/home/iaw/soft/qbics/v2025.12.15-GCC8.1.0-OPENMPI4.1.6-CMAKE3.15.0`
- executable: `qbics-linux-cpu-mpi`
- typical tmp: `/home/iaw/.CACHE/QBICS`

QBICS environment pattern:

```bash
export PATH=/home/iaw/soft/gcc/8.1.0_glibc2.17/bin:$PATH
export LD_LIBRARY_PATH=/home/iaw/soft/gcc/8.1.0_glibc2.17/lib64:${LD_LIBRARY_PATH:-}
export MPI_HOME=/home/iaw/soft/Openmpi/4.1.6
export PATH=$MPI_HOME/bin:$PATH
export LD_LIBRARY_PATH=$MPI_HOME/lib:$LD_LIBRARY_PATH
export OMPI_MCA_btl=vader,self
export QBICS_HOME=/home/iaw/soft/qbics/v2025.12.15-GCC8.1.0-OPENMPI4.1.6-CMAKE3.15.0
export PATH=$QBICS_HOME:$PATH
```

Remote command construction:

- Prefer `scripts/run_remote_gaussian.py` for Gaussian. It builds login-host to
  compute-host SSH commands with `remote/exec.py` and submits through
  `remote/job_runner.py`, using local `subprocess.run(..., shell=False)` and a
  single final compute-host `bash -lc` command.
- Keep engine semantics out of the generic SSH and job lifecycle boundaries.
  `remote/job_runner.py` owns directory preparation, background submit,
  PID/metadata receipt files, node-output status/tail/fetch snippets, and
  downloads. Download fallback first checks remote file existence; network,
  login, or permission failures must surface instead of silently falling back to
  stale legacy artifacts. `run_remote_gaussian.py` is the Gaussian adapter over
  that layer; xTB or ASE/NEB remote execution must provide engine-specific
  adapters instead of reusing the Gaussian CLI.
- For ad hoc compute-host commands that need shell operators, generate the SSH
  argv through `OpenSSHRemoteExecutor.compute_argv(...)` instead of hand-writing
  nested quotes:

```bash
python - <<'PY'
from pathlib import Path

from transition_state_workflow.remote.exec import (
    OpenSSHRemoteExecutor,
    RemoteTarget,
    command_text,
)

executor = OpenSSHRemoteExecutor(
    RemoteTarget("iaw.1w", "compute-0-30", Path("/home/iaw/.ssh/config"))
)
command = (
    "cd /home/iaw/codex_runs/<run> && "
    "nohup bash scripts/<job>.sh > logs/<job>.nohup 2>&1 < /dev/null & "
    "echo $!"
)
print(command_text(executor.compute_argv(command)))
PY
```

Always verify with:

```bash
python - <<'PY'
from pathlib import Path

from transition_state_workflow.remote.exec import (
    OpenSSHRemoteExecutor,
    RemoteTarget,
    command_text,
)

executor = OpenSSHRemoteExecutor(
    RemoteTarget("iaw.1w", "compute-0-30", Path("/home/iaw/.ssh/config"))
)
command = "hostname; ps -ef | grep -E 'g16|qbics|mpirun|<job>' | grep -v grep || true"
print(command_text(executor.compute_argv(command)))
PY
```
