# CF22D readiness

Before first use or after changing the bound environment, prepare `chemical.cf22d-doctor@1` with `research_agent.application.executors` and submit the file to a bounded job_start. Its declared entry uses the configured PySCF interpreter and activation. It checks PySCF, geomeTRIC, dispersion dependencies and actual CF22D/D3 construction without running an SCF or optimization. Save stdout as readiness evidence.

job_probe only checks platform availability. Run the doctor in the selected local or remote environment; local success does not prove remote readiness. The research_agent.application.executors helper resolves installation bindings for calculation requests. Do not install dependencies into a shared environment during a research job.

Readiness does not validate a scientific result or promise convergence. Failures report the underlying dependency error; fix the environment before resubmitting.
