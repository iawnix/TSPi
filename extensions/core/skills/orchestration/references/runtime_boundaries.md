# Runtime, Research State and Monitor boundaries

Research State is the sole authority for Claims, Nodes, dependencies, strategies,
checkpoints and workspace research liveness. Use the registered research tools;
never maintain a second workflow state file. Session memory is conversation
history; memory/index.json is a rebuildable State projection.

Host binds workspace/session identity, queues inputs and executes the Pi loop.
State returns durable tool admission; the Harness serializes tool calls and records phase labels without a second workflow admission graph.
Read the State-provided ready_node_ids and blocked_node_ids before continuing.
Do not reconstruct lifecycle rules from chat history or old status aliases.

Job Runtime owns process/scheduler identity, logs, status, cancellation and file
collection. The State bridge links Jobs to Attempts. Skill scripts own scientific
input generation, parsing and validation. artifact_derive records a descriptor;
it does not execute analysis. Run analysis scripts and register their real files.

Monitor observes Job changes and queues a deduplicated next_run event to the
owning session. It does not collect scientific outputs, interpret results, change
research Nodes, choose calculations or send email. State decides wake admission;
a deferred event remains pending until State changes, without repeated prompts.
After a wake, read State, then use job_status/job_collect/job_reconcile as needed.

Block a Node requiring user input with research_change and give a concrete
reason. Independent Nodes may continue. If other Attempts run, use
waiting_external with their real Attempt IDs. A global user_input_required
checkpoint is valid only when scoped Nodes are blocked/closed and no independent
ready or running work remains. An email recipient is not a calculation dependency.
Use a recovery checkpoint after the actual user decision, then update Nodes.

The public tool schema is the interface contract. Read [public_contract.md](public_contract.md)
for generated tool names and dispositions; Skills describe how to use that contract,
not a separate scheduler or capability registry.


State persists `continuation` in its liveness projection only for an explicit
continue_required checkpoint with an owning session. Host consumes that outbox
through its existing durable input receipts. Unchanged revisions cannot create
new wakes; continuation budget is State-owned. Monitor remains responsible only
for Job changes and configured queue-wait threshold events. `eligible_node_ids`
means dependency/strategy admission; `ready_node_ids` excludes running scopes.
An independent workId can admit another Job in an eligible running scope without
making it an automatically ready plan. Neither Skill nor Host reconstructs this rule.
