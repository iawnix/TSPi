# Pi Runtime Adapter

Pi supplies the single model/tool loop. TSPi adds Research State context and
 durable Job and Artifact tools; it does not create Compute or Review agents.

The Root session uses:

```text
research_read
research_change
research_strategy
research_interpretation
research_checkpoint
job_start / job_status / job_collect / job_cancel / job_reconcile
artifact_register / artifact_create / artifact_read / artifact_derive / artifact_link
```

Domain Skills describe how to construct commands and interpret outputs. The
Root combines those instructions with ordinary Pi tools and records evidence
in Research State. A completed job is only an execution receipt until its raw
outputs are registered as Artifacts and interpreted into Findings.
