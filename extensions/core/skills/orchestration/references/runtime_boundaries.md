# Runtime, Research State and Monitor boundaries

Research State owns user requirements, research decisions and liveness. Read its
current projection to decide what work is ready or blocked. Use public tools for
changes; conversation history and memory projections do not replace State.

Host owns identity, client connections and routing. Pi Harness/Worker owns input
admission, queues, interruption and durable submissions. This shared admission
path receives terminal, phone and authenticated internal events. State supplies
research admission decisions; Skills explain choices within those decisions.

Job Runtime owns processes, schedulers, logs, cancellation and file collection.
The State bridge associates each Job with its Attempt. Domain extensions declare
scientific executors and validators; their Skills explain method choice and result
interpretation. An artifact_derive descriptor describes analysis but does not run
it. Execute the analysis as a Job before using its outputs as evidence.

Monitor observes Job changes and places events in the owning session's outbox.
Worker admits an event against current State and records the Pi submission. A
pending event is not proof that the model has consumed it. Monitor does not collect
outputs, interpret science, select methods or send email. After a wake, inspect
State and use job_status, job_collect or job_reconcile as appropriate.

State owns explicit continuation requests and their budget. Worker admits them
through the same durable input path. Neither Host nor Skill reconstructs a second
research scheduler. See the [generated public contract](public_contract.md) for
available tools and checkpoint dispositions.

Scope blockers to the work they affect. Missing delivery details need not stop
independent calculations. Continue ready work, wait for actual running Attempts,
and request user input when a decision is needed to proceed. After the user's
answer, record recovery and update the affected Nodes before restarting work.
