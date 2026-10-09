# Execution environment selection

`TSPI_PYTHON` is the installation's control interpreter. Use it to prepare
requests and format existing evidence. It does not supply scientific libraries.

Select an installed executor and a named environment from `job.toml`. The
executor declares its dependencies; the selected binding supplies the target
Python or native program. Structure preparation and chemical validators can
share the `structure.lock` environment. Gaussian/xTB Python wrappers use
`wrapper.lock`; CF22D uses `cf22d.lock`; molecular rendering uses `render.lock`.
These locks are installation resources under the chemical extension's
`environments` directory. They do not prescribe which scientific method to use.

Preparation checks the selected target and fixes input, script and environment
identities. Submission and execution recheck that identity. A missing binding,
dependency or verified receipt is an installation gap, not permission to run
science in the Host interpreter or silently choose another method.

Record the unmet requirement and report the concrete missing binding. An
operator can install a versioned prefix from the shipped lock with
`scripts/install_job_environment.py`; a research task must not modify shared
environments. Existing jobs retain their original identities after maintenance.
