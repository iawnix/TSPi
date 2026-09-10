import type { ModelRuntime } from "@earendil-works/pi-coding-agent";

export type ModelReadinessProblem =
  | "model_unavailable"
  | "model_auth_missing"
  | "model_storage_unavailable"
  | "model_check_failed";

/** Classify failures without exposing provider configuration or credentials. */
export function modelReadinessFailure(error: unknown): ModelReadinessProblem {
  const visited = new Set<unknown>();
  while (error != null && !visited.has(error)) {
    visited.add(error);
    const record = typeof error === "object" ? error as { code?: unknown; message?: unknown; cause?: unknown } : undefined;
    const code = record?.code;
    const message = typeof error === "string" ? error : record?.message;
    if (["EROFS", "EACCES", "EPERM", "ELOCKED"].includes(String(code))
      || typeof message === "string" && /\b(?:EROFS|EACCES|EPERM|ELOCKED)\b|read-only file system/i.test(message)) {
      return "model_storage_unavailable";
    }
    error = record?.cause;
  }
  return "model_check_failed";
}

export function requireRuntimeModel(
  runtime: Pick<ModelRuntime, "getModel" | "hasConfiguredAuth" | "getError">,
  selected: { provider: string; id: string },
) {
  let problem: ModelReadinessProblem;
  try {
    const model = runtime.getModel(selected.provider, selected.id);
    if (model && runtime.hasConfiguredAuth(model.provider)) return model;
    const error = runtime.getError();
    problem = error ? modelReadinessFailure(error) : model ? "model_auth_missing" : "model_unavailable";
  } catch (error) {
    problem = modelReadinessFailure(error);
  }
  throw new Error(`${problem}: Child model is not ready: ${selected.provider}/${selected.id}`);
}
