import { readFileSync, realpathSync } from "node:fs";
import { resolve, relative, isAbsolute } from "node:path";
import { createHash } from "node:crypto";

/** Resolve a workspace-owned immutable Job request, before State admission. */
export function resolvePreparedJob(params, root) {
  if (!params.requestFile) return params;
  const base = realpathSync(root);
  const path = realpathSync(resolve(base, params.requestFile));
  const child = relative(base, path);
  if (child.startsWith("..") || isAbsolute(child)) throw new Error("prepared Job must be inside the workspace");
  for (const key of Object.keys(params)) {
    if (!["requestFile", "requestSha256", "nodeId", "timeoutSeconds", "root"].includes(key)) {
      throw new Error(`prepared Job cannot override ${key}; edit and re-prepare the request`);
    }
  }
  const bytes = readFileSync(path);
  if (bytes.length > 1_000_000) throw new Error("prepared Job exceeds 1 MB");
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (params.requestSha256 !== digest) throw new Error("prepared Job digest mismatch; inspect the current request before submitting");
  const request = JSON.parse(bytes);
  const allowed = ["requestId", "workId", "command", "platform", "environment", "inputs", "outputs", "metadata", "timeoutSeconds"];
  if (!request || Array.isArray(request) || Object.keys(request).some(key => !allowed.includes(key))
      || typeof request.requestId !== "string" || !request.requestId || !Array.isArray(request.command) || !request.command.length) {
    throw new Error("invalid prepared Job request");
  }
  return { ...request, ...(params.nodeId ? { nodeId: params.nodeId } : {}),
    ...(params.timeoutSeconds ? { timeoutSeconds: params.timeoutSeconds } : {}), root };
}
