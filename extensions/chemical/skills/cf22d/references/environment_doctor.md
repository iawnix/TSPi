# CF22D readiness

Before first use or after changing the bound environment, stage [doctor.py](../scripts/doctor.py) with all cf22d/scripts modules in a bounded job_start using the configured PySCF interpreter and activation. It checks PySCF, geomeTRIC, dispersion dependencies and actual CF22D/D3 construction without running an SCF or optimization. Save stdout as readiness evidence.

job_probe only checks platform availability. Run the doctor in the selected local or remote environment; local success does not prove remote readiness. The prepare_job.py helper resolves installation bindings for calculation requests. Do not install dependencies into a shared environment during a research job.

Readiness does not validate a scientific result or promise convergence. Failures report the underlying dependency error; fix the environment before resubmitting.
