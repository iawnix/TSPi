/** Payload bytes and Research State manifests share one evidence boundary. */
export function createEvidenceRuntime({ bridge } = {}) {
  if (typeof bridge?.execute_command !== "function") throw new TypeError("evidence runtime requires the workspace command bridge");
  return Object.freeze(Object.fromEntries([
    "register", "create", "read", "derive", "link",
  ].map((operation) => [`artifact_${operation}`, (params = {}) => bridge.execute_command(`artifact.${operation}`, params)])));
}
