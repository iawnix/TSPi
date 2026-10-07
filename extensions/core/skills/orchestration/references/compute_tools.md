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
directory. It creates a durable receipt and captures stdout and stderr. It does
not select a scientific method, parse output, validate a Claim, or create a
Finding automatically.

Use `job_status` while a process is running. Use `job_reconcile` after a monitor
wake or service restart when the receipt state is uncertain. Use `job_collect`
only after the job reaches a terminal state. Register each meaningful output with
`artifact_register`; create a Finding with `research_change` and cite the
Artifact as a source reference.

A Skill may describe Gaussian, xTB, PySCF, or any other program. The Skill may
also provide scripts and validation references. Those instructions are data for
Root's normal Pi loop; they are not provider descriptors or capability gates.

A successful exit code is an execution fact only. It does not establish that a
calculation converged, that a parser accepted the output, or that a Claim is
supported.
