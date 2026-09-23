# Remote Execution Contract

`ts_calc` owns the calculation lifecycle for both local and remote targets.
The remote adapter is the installation-bound OpenSSH/SCP and Torque transport;
it is not a second public calculation lifecycle. The public environment query
is `compute.environments`, exposed as `/compute` and `ts_environment`.

## Installation-Owned Policy

`compute.toml` is the recommended shared policy file. Each environment declares a
`kind` and a `backends` table; `kind = "remote"` environments additionally own SSH
host/config, remote root, scheduler commands, queues, resource ceilings,
activation, scratch policy, and process environment. Local and remote environments
are defined in this one file; there is no separate remote registry. A calculation
request selects a named environment and resources within its configured limits.

Use the installation-level `TSPi --check-remote` command for read-only diagnostics:

- `status`: SSH connectivity only;
- `doctor`: SSH, scheduler, storage, and registered software;
- `queues`: bounded queue view;
- `nodes`: bounded compute-resource view.

Run `TSPi --check-remote` before the first remote calculation or after
configuration changes.
For `ase_neb`, `doctor` additionally imports ASE and the TSPi runner with the
configured Python and executes the configured xTB program's version probe. The
environment is ready only when all three components are available.
For `pyscf`, bind a dedicated Python interpreter and activation script that
contain PySCF, geomeTRIC, `pyscf-dispersion`, and the TSPi runner; the doctor
also probes a `CF22D` DFT constructor. The PySCF kernel does not install or
discover scientific packages from the host Python during a calculation.

## Isolation

Remote directories are derived from workspace identity, ResearchNode, and
intent. The upload manifest binds regular files, sizes, SHA-256, command, environment,
resources, expected artifacts, and submission ID. Remote files provide the
execution copy; collection downloads declared outputs into the local workspace.

## Control Lifecycle

Submit persists pre-effect staging state before calling Torque. Once the
scheduler request begins, transport failure may be ambiguous. Preserve any
known job ID and durable submission record even if later queue/history lookup
fails.

Cancel similarly distinguishes known no-effect, known cancellation, and
ambiguous effect. When a job disappears from the queue, inspect its receipt
and declared outputs to establish what happened.

Inspect may combine durable receipt, scheduler state, program status, and a
bounded declared artifact tail. Collection follows the immutable artifact
manifest and works even when scheduler history is unavailable.

## Verify Results

- Reconcile an unknown submit or cancel result before another control action.
- Resolve remote paths and commands from the configured environment and intent.
- Use `TSPi --check-remote` to check scheduler and software readiness as well as SSH.
- Check program termination and required outputs after scheduler completion.
- Collect outputs, verify them locally, and parse them before recording Findings.
