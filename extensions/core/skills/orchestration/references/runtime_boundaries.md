# Runtime, Host, Research State, Memory, and Monitor Boundaries

This reference defines the ownership boundary behind the public TSPi tools. It
is part of the agent-facing protocol; implementation modules and process names
do not create additional agent APIs.

## Agent Runtime

The Agent Runtime owns one conversation/session turn and the in-process
lifecycle lane. It routes a request to the workspace-bound Host and admits
tools according to the lifecycle phase (`orient`, `advance`, `prepare`,
`execute`, `interpret`, or `checkpoint`). A monitor wake starts in `wake` and
admits one orientation read before normal work can continue. The Runtime does
not choose a method, write a Claim or Node, or infer a scientific result.

The Runtime memory port is always session-scoped:

```json
{
  "schema_version": "agent_memory_read_1",
  "memory_scope": "session",
  "memory_authority": "agent_core_session",
  "entries": []
}
```

Conversation memory is not ResearchMap state. In a research workspace a
request for `scope=workspace` on the Agent Core memory port fails with
`research_memory_authority_required`; workspace scientific state must cross the
Research State boundary through `research_read`/`research_change` and typed lifecycle
commands.

## Host and App Server

The App Server is the transport and composition boundary. Before opening a
workspace-bound session or tool call, it must resolve an admitted
`workspace_manifest.json`; the process-wide Runtime may exist before that
binding, but a session cannot use it until the manifest is validated. A
missing, symlinked, mismatched, legacy, or partially admitted workspace fails
closed; the Host never derives identity from a filesystem basename or a legacy
store.

The Host binds `workspace_id`, `workspace_root`, and `workspace_mode` to the
request context. Agent parameters may select a ResearchMap object, capability,
Node, Artifact, or configured environment, but may not replace the bound root
or identity. Host-owned writes carry `principal=root_agent` and
`authority=kernel_write`; the Agent supplies rationale and operations, while
the Research State validates and commits them.

Public semantic tool names are the only Agent API:
`research_read`, `research_change`, `research_strategy`,
`research_interpretation`, `research_checkpoint`, `research_checkpoint`,
`Job Runtime platform configuration`, `Skill-provided method instructions`, `job_probe`, `job_start/job_status/job_collect`,
`artifact_derive`, and the artifact/review tools listed in
[pi_agent_adapter.md](pi_agent_adapter.md). Private source factory names and
slash commands are transport details and are not alternate protocols.

## Research State and Memory Projection

The Research State owns the canonical research documents and the atomic
revision. A successful `research_change` commits the context, liveness,
`memory/index.json`, and manifest revision as one workspace transaction. The
memory index is a bounded metadata/lifecycle projection; it is not conversation
memory and never becomes a second scientific authority. Root must inspect the
returned revision before relying on a change.

## Monitor

The Monitor owns operational polling and wake delivery for a bound calculation
Attempt. It may inspect scheduler/program state, collect declared outputs, and
enqueue a `next_run` wake when state changes. A wake is an operational trigger,
not a scientific instruction: it must not choose a method, mutate a Claim or
Node, or launch another calculation. The Root session rereads liveness and the
Attempt, then chooses `inspect`, `finalize`, `cancel`, interpretation, or a
checkpoint through the normal public tools.

## Compute Plane

Capability identity and execution environment are independent. Native Compute
descriptors use `capability_id` and `capability_version`; the analysis catalog
uses `capability` and `version`, and `artifact_derive` requests use
`capability` plus `capability_version`. These are two explicit catalog
contracts, not interchangeable aliases. The live catalog is the only source
of registered capabilities. `job_start/job_status/job_collect` is the calculation entry point for
both targets and uses `launch`, `inspect`, `finalize`, or `cancel`;
`artifact_derive` is deterministic local analysis and has no scheduler lifecycle.
Remote execution must use Native `job_start/job_status/job_collect` with a configured
`execution.environment`. There is no
generic capability invocation path: all descriptors come from the Python
Native registry, and the lifecycle schema is the only public calculation
request. The retired `capability_id` plus `input` form is rejected.
