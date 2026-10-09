# Job and material workflow

Prepare a domain request through its installed Skill. Submit the returned request_file and request_sha256 to job_start; use node_id for explicit research association. Other execution fields are pinned in the file. A direct argv command uses declared inputs, outputs and platform. No research object is required for preparation or diagnostics. Unassociated preparation and diagnostics remain available.

The adapter fixes the Node revision and actual inputs at submission. Later plan changes cannot change what an earlier Job tested. Job Runtime remains the source of dispatch and terminal facts. job_status observes, job_cancel requests cancellation, job_reconcile resolves uncertainty, and job_collect preserves outputs and provenance without executing again.

artifact_create stores new text, artifact_register imports a file, and artifact_read reads bounded bytes. Scientific Job outputs should be collected with their producer identity. Analysis requests declare and stage their actual inputs; validators run as ordinary Jobs. Reading a file does not establish scientific evidence usage.

Use research_update with node_id and note to explain what changed; use research_result with node_id and conclusion when there is a useful result to cite. Result files use registered artifact_ref values. Native work directories contain mutable drafts; a published result points to fixed materials. No research lifecycle transition is required before using a Job or native file tool.
