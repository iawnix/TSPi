# Job Runtime

TSPi uses the generic Job Runtime for scientific computation. Request preparation, report formatting and email use native bash with the installed Skill scripts. A Domain Skill explains
how to construct the command, inputs, expected outputs, and interpretation
criteria. Root executes that workflow with the Job and Artifact tools.

```text
job_probe -> job_start -> job_status -> job_collect
                         └-> job_cancel
                         └-> job_reconcile
```

`job_start` accepts an arbitrary argv vector and a workspace-relative working
directory; it does not require a scientific registry. For a domain-declared
executor, prepare it through native bash, then pass its returned
`request_file` and `request_sha256` with `node_id` to `job_start`. Execution
identity and parameters are already inside the file; adding a new request_id
or work_id at submission is rejected. Use the tool parameter contract for
other input forms. The Job creates a durable receipt and captures stdout and stderr. It does
not select a scientific method, parse output, validate a Claim, or create a
Finding automatically.

Use `job_status` while a process is running. Use `job_reconcile` after a monitor
wake or service restart when the receipt state is uncertain. Use `job_collect`
only after the job reaches a terminal state. Collection registers the declared
outputs and returns their Artifact references. Inspect those outputs, then cite
them when recording a meaningful Finding. Use `artifact_register` for material
not produced by collection, such as imported data or an externally supplied report.

A Skill may describe Gaussian, xTB, PySCF, or any other program. The Skill may
also provide scripts and validation references. Those instructions are data for
Root's normal Pi loop; they are not provider descriptors or capability gates.

A successful exit code is an execution fact only. It does not establish that a
calculation converged, that a parser accepted the output, or that a Claim is
supported.
