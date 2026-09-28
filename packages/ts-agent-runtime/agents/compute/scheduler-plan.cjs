"use strict";

// This is the Host scheduler protocol, not a capability registry.  A task
// may supply another plan (for example from a Skill descriptor); these
// defaults only describe the built-in calculation lifecycle adapter.
const DEFAULT_COMPUTE_SCHEDULER_PLANS = Object.freeze({
  launch: Object.freeze({
    required: Object.freeze([
      Object.freeze({ name: "prepare", tool: "ts_workspace_compute_prepare", fact_kind: "compute_preparation" }),
      Object.freeze({ name: "submit", tool: "ts_workspace_compute_submit", fact_kind: "submission" }),
    ]),
    optional: Object.freeze([]),
    primary: "submit",
  }),
  inspect: Object.freeze({
    required: Object.freeze([
      Object.freeze({ name: "status", tool: "ts_workspace_compute_status", fact_kind: "inspection" }),
    ]),
    optional: Object.freeze([
      Object.freeze({ name: "tail", tool: "ts_workspace_compute_tail", fact_kind: "inspection" }),
    ]),
    primary: "status",
  }),
  finalize: Object.freeze({
    required: Object.freeze([
      Object.freeze({ name: "collect", tool: "ts_workspace_compute_collect", fact_kind: "collection" }),
      Object.freeze({ name: "parse", tool: "ts_workspace_compute_parse", fact_kind: "parser" }),
    ]),
    optional: Object.freeze([]),
    primary: "parse",
  }),
  cancel: Object.freeze({
    required: Object.freeze([
      Object.freeze({ name: "cancel", tool: "ts_workspace_compute_cancel", fact_kind: "cancellation" }),
    ]),
    optional: Object.freeze([]),
    primary: "cancel",
  }),
});
const COMPUTE_RESULT_TOOL_NAME = "ts_compute_result";

function schedulerPlanFor(operation, supplied) {
  const raw = supplied === undefined || supplied === null
    ? DEFAULT_COMPUTE_SCHEDULER_PLANS[operation]
    : supplied;
  if (!isPlainObject(raw)) throw new Error("Compute task requires a scheduler action plan");
  const required = normalizeBindings(raw.required || raw.required_actions, "required");
  const optional = normalizeBindings(raw.optional || raw.optional_actions || [], "optional");
  const all = [...required, ...optional];
  if (!all.length) throw new Error("Compute scheduler action plan must contain an action");
  if (new Set(all.map((item) => item.name)).size !== all.length) {
    throw new Error("Compute scheduler action plan contains duplicate action names");
  }
  if (new Set(all.map((item) => item.tool)).size !== all.length) {
    throw new Error("Compute scheduler action plan contains duplicate tools");
  }
  const primary = requireIdentifier(raw.primary || raw.primary_action || all[all.length - 1].name, "primary");
  if (!all.some((item) => item.name === primary)) {
    throw new Error("Compute scheduler primary action is not declared");
  }
  return {
    required: required.map((item) => item.name),
    optional: optional.map((item) => item.name),
    bindings: all,
    primary,
  };
}

function normalizeBindings(value, label) {
  if (!Array.isArray(value) || value.length > 32) {
    throw new Error(`Compute scheduler ${label} actions must contain at most 32 items`);
  }
  return value.map((item, index) => {
    if (typeof item === "string") {
      // String plans are useful to Skills that bind tool names separately.
      return { name: requireIdentifier(item, `${label}[${index}]`), tool: item, fact_kind: "inspection" };
    }
    if (!isPlainObject(item)) throw new Error(`Compute scheduler ${label}[${index}] must be an object`);
    const name = requireIdentifier(item.name, `${label}[${index}].name`);
    const tool = requireIdentifier(item.tool, `${label}[${index}].tool`);
    const fact_kind = requireIdentifier(item.fact_kind || "inspection", `${label}[${index}].fact_kind`);
    return { name, tool, fact_kind };
  });
}

function requireIdentifier(value, label) {
  if (typeof value !== "string" || !value.trim() || value.length > 128 || !/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(value)) {
    throw new Error(`${label} must be a bounded action identifier`);
  }
  return value;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  COMPUTE_RESULT_TOOL_NAME,
  DEFAULT_COMPUTE_SCHEDULER_PLANS,
  schedulerPlanFor,
};
