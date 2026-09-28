/**
 * Execution ledger ports. ComputeService never depends on one of these
 * implementations; the Host selects the ledger from the admitted workspace
 * mode and injects it into the orchestration boundary.
 */

export const EXECUTION_LEDGER_VERSION = "execution_ledger_1";

function require_method(value, name) {
  if (!value || typeof value[name] !== "function") throw new TypeError(`execution ledger is missing ${name}()`);
}

function freeze_port(port) {
  for (const method of ["create_run", "mark_running", "mark_succeeded", "mark_failed"]) require_method(port, method);
  return Object.freeze({ protocol_version: EXECUTION_LEDGER_VERSION, ...port });
}

/** Adapt the bounded light run manifest store to the common ledger port. */
export function create_light_execution_ledger({ store } = {}) {
  if (!store) throw new TypeError("light execution ledger requires a run store");
  const update = (context, fields = {}) => store.update({
    workspace_root: context.workspace_root,
    run_id: context.run_id,
    ...fields,
  });
  return freeze_port({
    async read_run(context) { return store.read(context); },
    async create_run(context) { return store.create(context); },
    async mark_running(context) { return update(context, { state: "running" }); },
    async mark_succeeded(context) {
      return update(context, { state: "succeeded", input_artifact_ids: context.input_artifact_ids || [], output_artifact_ids: context.output_artifact_ids || [], result: context.result, metadata: context.metadata });
    },
    async mark_failed(context) {
      return update(context, { state: context.state || "failed", output_artifact_ids: context.output_artifact_ids || [], error: context.error });
    },
  });
}

/**
 * Adapt a Research Kernel port to the common ledger port. Scientific state
 * vocabulary is confined to this adapter; providers and ComputeService see
 * only create/running/succeeded/failed transitions.
 */
export function create_research_execution_ledger({ kernel, read_context, clock = () => new Date().toISOString() } = {}) {
  if (!kernel || typeof kernel.apply_change !== "function") throw new TypeError("research execution ledger requires kernel.apply_change()");
  const read = read_context || kernel.read_context;
  if (typeof read !== "function") throw new TypeError("research execution ledger requires read_context()");
  async function apply(context, operations) {
    const current = await read.call(kernel, { workspace_id: context.workspace_id, workspace_root: context.workspace_root });
    const revision = Number.isInteger(current?.revision) ? current.revision : 0;
    return kernel.apply_change({ workspace_id: context.workspace_id, workspace_root: context.workspace_root, expected_revision: revision, operations });
  }
  return freeze_port({
    async create_run(context) {
      return apply(context, [{ type: "create_attempt", id: context.run_id || context.attempt_id, node_id: context.node_id,
        capability: context.capability_id, capability_version: context.capability_version || "1", state: "started",
        environment: context.environment ?? null, input_artifact_ids: context.input_artifact_ids || [], output_artifact_ids: [], metadata: context.metadata || {} }]);
    },
    async mark_running(context) {
      return apply(context, [{ type: "transition_attempt", attempt_id: context.attempt_id || context.run_id, state: "running", updated_at: clock() }]);
    },
    async mark_succeeded(context) {
      const id = context.attempt_id || context.run_id;
      const operations = [...(context.artifact_operations || []), { type: "transition_attempt", attempt_id: id, state: "succeeded", updated_at: clock(), output_artifact_ids: context.output_artifact_ids || [], metadata: context.metadata || {} }, ...(context.evidence_operations || [])];
      return apply(context, operations);
    },
    async mark_failed(context) {
      const id = context.attempt_id || context.run_id;
      return apply(context, [{ type: "transition_attempt", attempt_id: id, state: context.state || "failed", updated_at: clock(), output_artifact_ids: context.output_artifact_ids || [], error: context.error, error_class: context.error?.code, exit_code: context.exit_code ?? null }]);
    },
  });
}
