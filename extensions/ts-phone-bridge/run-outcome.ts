export type RunOutcome =
  | { status: "completed" | "cancelled" }
  | { status: "failed"; problem: string; httpStatus?: number };

/** Project diagnostics without copying provider bodies, credentials or URLs. */
export function assistantOutcome(message: unknown): RunOutcome | undefined {
  if (!message || typeof message !== "object") return undefined;
  const value = message as Record<string, unknown>;
  if (value.role !== "assistant") return undefined;
  if (value.stopReason === "aborted") return { status: "cancelled" };
  if (value.stopReason === "stop") return { status: "completed" };
  if (value.stopReason === "length") return { status: "failed", problem: "generation_incomplete" };
  if (value.stopReason !== "error") return undefined;
  const error = typeof value.errorMessage === "string" ? value.errorMessage : "";
  // Pi's OpenAI adapters prefix API errors with the HTTP status. Do not infer
  // status codes from arbitrary numbers in a nested provider response.
  const match = /^\s*([45]\d{2})(?=[:\s])/.exec(error);
  const httpStatus = match ? Number(match[1]) : undefined;
  const problem = httpStatus === 429 ? "provider_rate_limited"
    : httpStatus !== undefined && httpStatus >= 500 ? "provider_unavailable"
    : httpStatus === 401 || httpStatus === 403 ? "provider_auth_failed"
    : "provider_error";
  return { status: "failed", problem, ...(httpStatus ? { httpStatus } : {}) };
}
