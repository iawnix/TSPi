# Scientific Job contract

A domain extension owns scientific inputs, argv, parsing and validation. Its execution catalog declares convenience entries; its Skills explain when to use them and how to interpret results.

## Submission

Use `"$CORAGENT_PYTHON" -m research_agent.application.executors` to combine an installed executor with a named job.toml binding. It writes a request containing argv, platform, process environment, pinned inputs and required outputs. Inspect the file, then pass its returned request_file/request_sha256 with optional timeout_seconds to job_start. Configure resource defaults in job.toml before preparing. Runtime registers prepared_ref together with the dispatch intent and Job; the preparation command does not write Research Memory.

Inputs are snapshotted with paths and digests. Keep script module layout intact. Runtime owns local/remote process control; Skill scripts may synchronously launch the scientific executable inside the Job but must not detach or submit their own scheduler jobs.

## Environment

job_probe checks the selected platform, not scientific readiness. The configured command and activation_script determine the actual executable. Prepare the declared `chemical.cf22d-doctor` executor as a Job for CF22D dependency/method checks in each selected environment. Remote wrapper Python must be explicitly bound. Do not substitute system Python or change the scientific method when dependencies are missing.

## Evidence

Record the observations, scientific criteria, unresolved questions and next steps with research_update using the existing node_id and a note. Publish a reusable conclusion with research_result, citing collected materials and stating limitations. A completed computation does not establish a scientific conclusion.

artifact_derive records a derivation descriptor; it does not execute analysis. Run a Skill script then register its actual output. artifact_link persists evidence relations. Changed scientific inputs/settings create a new Job; recovery of an uncertain submission uses job_reconcile, not automatic resubmission.

The catalog constrains selected registered helpers only. Generic `job_start` also accepts explicit command, inputs, outputs, and platform; task-specific Python methods can use the preparer's `--script` and `--backend` without a new catalog entry.
