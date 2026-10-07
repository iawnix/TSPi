# Scientific Job contract

A Skill owns scientific inputs, argv, parsing and validation. Use its installed scripts; no scientific registry or workflow catalog is required.

## Submission

Use method-selection/scripts/prepare_job.py to read job.toml bindings. It returns command (argv), platform (configured execution target), environment (process variables), inputs (source/destination file or directory mappings), outputs (path, required, minBytes, mediaType) and opaque metadata. Add nodeId, timeoutSeconds and any supported metadata.resources (cpus, memory_mb, walltime) before job_start. cwd is a relative subdirectory of the isolated Job root, not an arbitrary workspace directory.

Inputs are snapshotted with paths and digests. Keep script module layout intact. Runtime owns local/remote process control; Skill scripts may synchronously launch the scientific executable inside the Job but must not detach or submit their own scheduler jobs.

## Environment

job_probe checks the selected platform, not scientific readiness. The configured command and activation_script determine the actual executable. Use cf22d/scripts/doctor.py for CF22D dependency/method checks; run it in each selected environment. Remote wrapper Python must be explicitly bound. Do not substitute system Python or change the scientific method when dependencies are missing.

## Evidence

job_start returns distinct job_id and attempt_id. Use the real Attempt for waiting checkpoints. job_collect returns exit facts, output_validation and registered Artifacts for research Jobs. Exit 0, complete files and scientific validation are separate facts. Read the Skill result.json and logs before registering Findings.

artifact_derive records a derivation descriptor; it does not execute analysis. Run a Skill script then register its actual output. artifact_link persists evidence relations. Changed scientific inputs/settings create a new Attempt; recovery of an uncertain submission uses job_reconcile, not automatic resubmission.
