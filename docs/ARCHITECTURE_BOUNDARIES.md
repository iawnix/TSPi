# Execution and evidence boundaries

Scientific and email capabilities belong to Skills: instructions, executable scripts,
input templates, parsers and validation. The installed chemical Skills provide
CF22D, GFN2-xTB and Gaussian opt/SP runners. Skills can use ordinary shared libraries;
there is no scientific capability registry or Provider dispatch in their execution path.

Job Runtime executes arbitrary argv locally or through SSH/PBS. It owns durable
process/scheduler identity, logs, timeout/cancellation, status and file collection.
The local supervisor writes terminal receipts even when the Host is not polling.
A process exit code, required-output completeness, and scientific validity are
separate facts. Runtime never interprets a method or energy.

The TSPi adapter snapshots inputs in an isolated Job directory and binds research
Jobs to real Attempts through the Research State transaction writer. Collected
files are registered in Artifact Store and associated with the producing Attempt.
The Agent interprets scientific evidence and registers Findings. A plan is not an
Attempt; a Job ID is not an Attempt ID; storing a payload is not a scientific claim.

Monitor maintains a durable wake outbox for the owning session. It does not send
email. The email Skill uses local Jobs, installation credentials and stable delivery
identities; unknown delivery outcomes require reconciliation rather than blind retry.

Extension manifests discover Skills. providers remains readable for legacy/third-party
metadata but is optional and absent from the chemical and email manifests. Executable
Skill resource indexes are digest-pinned and verified when the extension is loaded.
Old scientific Provider implementations must be split before retirement: migrate
scientific algorithms and their tests into Skills, move process control into Runtime,
and remove protocol/registry glue. Deleting a Provider directory is not evidence that
its scientific functionality has been migrated.
