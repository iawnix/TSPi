# Scientific Job contract

A domain extension owns scientific inputs, argv, parsing and validation. Its manifest declares executable entries; its Skills explain when to use them and how to interpret results.

## Submission

Use `"$TSPI_PYTHON" -m tspi_runtime.executors` to combine an installed executor with a named job.toml binding. It writes a request containing argv, platform, process environment, pinned inputs and required outputs. Inspect the file, then pass its returned request_file/request_sha256 with node_id and optional timeout_seconds to job_start. Configure resource defaults in job.toml before preparing. Runtime registers prepared_ref together with the dispatch intent and Attempt; the preparation command does not write Research State.

Inputs are snapshotted with paths and digests. Keep script module layout intact. Runtime owns local/remote process control; Skill scripts may synchronously launch the scientific executable inside the Job but must not detach or submit their own scheduler jobs.

## Environment

job_probe checks the selected platform, not scientific readiness. The configured command and activation_script determine the actual executable. Prepare the declared `chemical.cf22d-doctor` executor as a Job for CF22D dependency/method checks in each selected environment. Remote wrapper Python must be explicitly bound. Do not substitute system Python or change the scientific method when dependencies are missing.

## Evidence

job_start returns distinct job_id and attempt_id. Use the real Attempt for waiting checkpoints. job_collect returns exit facts, output_validation and registered Artifacts for research Jobs. Exit 0, complete files and scientific validation are separate facts. Read the Skill result.json and logs before registering Findings.

artifact_derive records a derivation descriptor; it does not execute analysis. Run a Skill script then register its actual output. artifact_link persists evidence relations. Changed scientific inputs/settings create a new Attempt; recovery of an uncertain submission uses job_reconcile, not automatic resubmission.
