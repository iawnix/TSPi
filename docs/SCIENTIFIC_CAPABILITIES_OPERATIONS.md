# Scientific execution and operations

[简体中文](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)

`domains/chemical/execution.json` declares bundled convenience executors and validators. Skills explain method selection, scientific limitations and interpretation. Research Memory records original requirements, research questions and results; adding an executor does not require method-specific research fields.

These entries are not a workflow or a capability allowlist. The Agent can prepare
native commands or task scripts and execute generic Jobs without registering a
new entry for each calculation. See [Skills and the execution catalog](EXTENSIONS.md).

## Prepare and execute

List installed entries with `"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --list`. Select an executor id/version and a named environment from installation-owned `etc/job.toml`. The descriptor supplies its backend key, pinned scripts, pure CLI parser, input roles and output declarations. Native entries need no Python binding; Python entries use the selected target's configured interpreter.

The preparation command writes a request and returns `request_file` and `request_sha256`. Submit these to `job_start`, supplying `node_id` when associating a research question. Runtime checks the file and inputs and fixes the selected Node association and content revision, `prepared_ref` and dispatch intent. Preparation alone dispatches no Job and proves no scientific outcome.

A task-specific Python method can use `--script <file.py> --backend <binding>` instead of executor/version. Declare staged dependencies and collected outputs. For registered input evidence, pass `--input-artifact <id-or-ref>` so Runtime verifies its actual staged bytes and preserves lineage.

Recover a lost response with the original request identity. Use `job_status`, `job_reconcile` and `job_collect`; a timeout or disconnected client does not authorize another submission. Intentional repetition needs a new identity and the predecessor/reason/budget declaration.

## Platform checks

Use `job_probe` in a session to inspect a configured platform. Maintainers can
verify software bindings from the installed control environment:

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.environment_check --config "$RESEARCH_AGENT_JOB_CONFIG"
```

This checks configured environments and may contact their SSH targets. Platform
observations from `job_probe` and software dependency checks are distinct.

## Environments and ownership

The selected job.toml backend provides the command, Python binding, activation and resource defaults. Structure generation uses the chemical extension's `structure` backend; registered chemical validators use `validation`. Executors and validators can declare `requirements`: Python version specifiers in `python` and `packages`, and modules to actually import in `imports`. Native entries do not declare Python dependencies.

Preparation probes the selected local or SSH target: interpreter prefix, explicit Conda lock, pinned pip versions, installation receipt, package inventory, executable and activation file digests. This observation contributes to request identity. New submissions recheck it, and the staged, digest-pinned guard checks again when execution begins. Activation is verified before sourcing. Drift prevents execution; retries of an existing Job still return its original identity. Environment agreement does not itself prove a scientific method works.

Installation receipts now include `inventory_sha256`. Reverify an existing environment using `scripts/install_job_environment.py --config … --environment … --backend … --adopt` before publishing a new receipt; do not hand-fill a digest. The installer first validates configuration structure, then uses the installed control runtime and extension catalog to run `"$RESEARCH_AGENT_PYTHON" -m research_agent.application.environment_check --config "$RESEARCH_AGENT_JOB_CONFIG"` for all configured entries, including remote targets. `job_probe` continues to describe platform availability only.

Application-submitted local Jobs run in independent transient systemd user services. They survive Host restarts, receive a minimal environment plus explicit Job variables, and use CPUQuota/MemoryMax when resources are requested. Runtime creates a private scratch directory inside the Job or below the configured scratch_root; explicit environment values can reference `{scratch}`. Receipts remain in the workspace after a transient unit is removed.

Resource defaults merge once at preparation or submission, in target, backend, then explicit-request order. Prepared entries keep their resolved resources; submission cannot override them. The Job receipt and execution fingerprint record the actual values. `allowed_queues` is a permission boundary, not a default for `submission.queue`. Local targets reject queue fields. Torque translates cpus/memory_mb to nodes/ppn and mem; PBS uses select (which cannot be combined with cpus/memory_mb). When both walltime and program timeout_seconds are present, the shorter limit applies.

Remote Jobs use the configured SSH/PBS target and share the local minimal process environment, thread defaults and scratch rules. They do not inherit scientific settings from the login shell: required paths and activation scripts belong in the binding. Remote directory names include a digest of the local Job path, keeping same-name Jobs in different workspaces separate. Recovery uses the saved actual directory and scheduler.id; historical directories are used only to recover their original tasks.

`command_timeout_seconds` limits SSH control commands (60 seconds by default); `transfer_timeout_seconds` separately limits each rsync operation (3600 seconds by default). Neither is the scientific program's execution deadline. Collection excludes the local spec, receipt, status and other control files so calculation outputs cannot overwrite them. Solver completion and successful output collection remain separate observations.

Submission disables scheduler mail and automatic reruns; the research workflow owns notifications and intentional repeats. Successful `qdel` records a cancellation request. The Job becomes cancelled only after a terminal scheduler state or confirmation that its record has been removed. Connection failures during cancellation remain unknown; a program that finishes first retains its actual exit result.

## Evidence and support boundaries

Job files live below `runs/jobs/<job_id>`. Collection registers declared files as Artifacts belonging to their producing Job, including all files in an explicitly declared recursive output directory. The Agent applies domain methods, records interpretation in the corresponding Node and publishes useful Results. Exit zero or a formatted report alone does not establish scientific success.

Bundled executable entries cover CF22D, xTB, Gaussian inputs, structure/graph preparation, mapped DA candidates, IRC-input preparation and CF22D readiness. Gaussian's explicit-input runner also handles supported TS/Freq/IRC routes. CREST/QBICS guidance and NEB discussion do not imply a bundled callable runner: use a verified installed program or an explicitly bound task script and describe its actual scope.

The xTB convenience wrapper accepts `sp/opt/opt-sp`; frequencies, scans, and dynamics
use native commands through generic Jobs. See the [xTB Skill](../domains/chemical/skills/xtb/SKILL.md).
Specialized reaction-path checks do not cover every reaction; use the general
[transition-state criteria](../domains/chemical/skills/validation/SKILL.md).
See the [report Skill](../domains/chemical/skills/report/SKILL.md) for molecular images,
data tables, energy plots, and their evidence requirements.

## Validation

Use `tools/test/runner.py` to select the source, Native and package lanes. Real solver and remote acceptance use isolated workspaces and configured bindings. Synthetic Gaussian fixtures verify parsing and evidence linkage; they do not establish that a real transition-state search converges.
