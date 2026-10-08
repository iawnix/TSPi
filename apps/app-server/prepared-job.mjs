import { readFileSync, realpathSync } from "node:fs";
import { resolve, relative, isAbsolute } from "node:path";
import { createHash } from "node:crypto";

/** Resolve a workspace-owned immutable Job request, before State admission. */
export function resolvePreparedJob(params, root) {
  if (!params.request_file) return params;
  const base = realpathSync(root);
  const path = realpathSync(resolve(base, params.request_file));
  const child = relative(base, path);
  if (child.startsWith("..") || isAbsolute(child)) throw new Error("prepared Job must be inside the workspace");
  for (const key of Object.keys(params)) {
    if (!["request_file", "request_sha256", "node_id", "timeout_seconds", "repeat", "root"].includes(key)) {
      throw new Error(`prepared Job cannot override ${key}; edit and re-prepare the request`);
    }
  }
  const bytes = readFileSync(path);
  if (bytes.length > 1_000_000) throw new Error("prepared Job exceeds 1 MB");
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (params.request_sha256 !== digest) throw new Error("prepared Job digest mismatch; inspect the current request before submitting");
  const request = JSON.parse(bytes);
  const allowed = ["request_id", "work_id", "command", "platform", "environment", "inputs", "outputs", "metadata", "timeout_seconds"];
  if (!request || Array.isArray(request) || Object.keys(request).some(key => !allowed.includes(key))
      || typeof request.request_id !== "string" || !request.request_id || !Array.isArray(request.command) || !request.command.length) {
    throw new Error("invalid prepared Job request");
  }
  return { ...request, ...(params.node_id ? { node_id: params.node_id } : {}),
    ...(params.repeat ? { repeat: params.repeat } : {}),
    ...(params.timeout_seconds ? { timeout_seconds: params.timeout_seconds } : {}), root };
}
