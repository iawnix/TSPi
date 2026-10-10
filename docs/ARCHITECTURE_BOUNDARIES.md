# Execution and research boundaries

Research Memory stores local problem Nodes, immutable Results, explicit relations and original requirements. It does not own Job state, Artifact bytes, scientific validation or email transport. The [architecture](ARCHITECTURE.md) specifies the current contract and implementation status.

Skills contain methods, executable scripts, templates and parsers. Generic Job Runtime executes explicit argv locally or through SSH/PBS and owns dispatch, status, cancellation and collection. The CoRAgent adapter fixes actual inputs and optional Node/revision association. The platform launcher does not import Memory or infer a scientific plan.

Collection registers materials with producing Job and input provenance. ResearchResult references fixed materials and recorded executions; the Agent distinguishes observations, scientific judgments and limitations. Process success and required-file completeness do not prove a hypothesis.

Monitor next_run owns durable event delivery to the original session, independently of Memory sequence. Host/Pi owns admission and input consumption. No research checkpoint is required at turn end; Memory changes neither grant tool access nor initiate model turns.

Email uses its own preparation, send identity, receipt and uncertain-outcome recovery. A failed research projection cannot cause another send. Execution catalogs pin executable resources; validators run as ordinary Jobs and do not impose generic scientific lifecycle transitions.
