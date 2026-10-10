# Execution and research boundaries

Research Memory stores local problem Nodes, immutable Results, explicit relations and original requirements. It does not own Job state, Artifact bytes, scientific validation or email transport. The [architecture](ARCHITECTURE.md) specifies the current contract.

Skills contain methods, executable scripts, templates and parsers. Generic Job Runtime executes explicit argv locally or through SSH/PBS and owns dispatch, status, cancellation and collection. The CoRAgent adapter fixes actual inputs and optional Node/revision association. The platform launcher does not import Memory or infer a scientific plan.

Collection registers materials with producing Job and input provenance. ResearchResult references fixed materials and recorded executions; the Agent distinguishes observations, scientific judgments and limitations. Process success and required-file completeness do not prove a hypothesis.

Monitor is the unified task and Job supervision surface. Its Job worker owns durable event delivery to the original session, independently of Memory sequence. Its Task Controller lives inside the Pi SessionWorker and owns persistent user intent, waits, pause/resume/cancel and bounded continuation policy. Pi remains the only Agent execution loop and owner of submissions, execution status and recovery. A final model reply does not complete the user task.

All Monitor controls use one canonical Host method set and one `coragent.monitor.handle` Worker service. Task state and control receipts share the Pi transaction; Host only routes them. Job ownership uses an immutable `user_task_id` association alongside independent Node/revision links. No research checkpoint is required at turn end; Memory changes neither grant tool access nor initiate model turns. Automatic task continuations use trusted provenance and the existing admission boundary, never synthetic user authorization.

Host discovers recovery candidates from Pi's session catalog without opening a second SQLite writer. Task overview, Job state and execution diagnostics are read projections of their respective owners. The [Monitor API contract](../contracts/monitor/README.md) is shared by TUI and browser clients; removed monitor enable/disable/status/list calls are not aliases.

Email uses its own preparation, send identity, receipt and uncertain-outcome recovery. A failed research projection cannot cause another send. Execution catalogs pin executable resources; validators run as ordinary Jobs and do not impose generic scientific lifecycle transitions.
