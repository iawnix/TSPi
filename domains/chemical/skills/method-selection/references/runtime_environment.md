# Execution environment selection

`CORAGENT_PYTHON` is the installation's control interpreter. Use it to prepare
requests and format existing evidence. It does not supply scientific libraries.

Use the method Skill to choose a recipe, native command or task script and a
named environment from `job.toml`. The selected binding supplies the target
Python or native program; a recipe also declares its own dependencies.
Structure preparation and chemical validators can
share the `structure.lock` environment. Gaussian/xTB Python wrappers use
`wrapper.lock`; CF22D uses `cf22d.lock`; molecular rendering uses `render.lock`.
These locks are installation resources under the chemical extension's
`environments` directory. They do not prescribe which scientific method to use.

Request preparation already checks the chosen target. For diagnosis before
preparation, check only the selected recipe and environment:

```bash
"$CORAGENT_PYTHON" -m research_agent.application.environment_check --config "$CORAGENT_JOB_CONFIG" --environment <name> --executor <id> --version <version>
```

For a native command or task script without a recipe, replace executor/version
with `--backend <binding>`. It checks the binding's Python and native program
when configured; `--runtime native` or `--runtime python` selects one runtime.
Only the chosen environment is contacted, including when it is remote.
`--details` adds the underlying observation for diagnosis.

`verified` means the selected prerequisites passed; a scientific Job supplies
the calculation result. `not_configured` identifies a missing environment or
backend. `check_failed` includes the actual binding/dependency/probe error.
`recipe_not_found` means only that the id/version has no predefined recipe;
consult the method Skill and check its backend, native command or task script.
The recipe index never determines software availability.

Preparation checks the selected target and fixes input, script and environment
identities. Submission and execution recheck that identity. A missing binding,
dependency or verified receipt is an installation gap, not permission to run
science in the Host interpreter or silently choose another method.

Record the unmet requirement and report the concrete missing binding. An
operator can install a versioned prefix from the shipped lock with
`scripts/install_job_environment.py`; a research task must not modify shared
environments. Existing jobs retain their original identities after maintenance.

A native prerequisite probe resolves and hashes the configured executable; it
does not run the solver or verify a license, convergence, or a scientific result.
`environment_executable_missing` means the selected command cannot be executed;
`environment_activation_missing` identifies its missing activation script;
`environment_dependency_missing` identifies a required package or module that is
absent. `environment_import_failed` means importing a present dependency failed
during initialization. Report the exact observation and selected target; an
unconfigured binding or absent recipe does not prove the software is absent
from every environment. Changed binding or executable evidence requires preparing
a new request before dispatch, not running an old prepared command.
