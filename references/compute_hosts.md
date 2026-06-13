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
  compute-host SSH commands with `remote_exec.py`, using local
  `subprocess.run(..., shell=False)` and a single final compute-host
  `bash -lc` command.
- For ad hoc compute-host commands that need shell operators, generate the SSH
  argv through `OpenSSHRemoteExecutor.compute_argv(...)` instead of hand-writing
  nested quotes:

```bash
python - <<'PY'
from pathlib import Path

from transition_state_workflow.util.remote_exec import (
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

from transition_state_workflow.util.remote_exec import (
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
