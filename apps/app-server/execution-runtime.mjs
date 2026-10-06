/** Job tools use the same Python command boundary as Research State. */
export function createExecutionRuntime({ bridge } = {}) {
  if (typeof bridge?.execute_command !== "function") throw new TypeError("execution runtime requires the workspace command bridge");
  return Object.freeze(Object.fromEntries([
    "start", "status", "collect", "cancel", "probe", "reconcile",
  ].map((operation) => [`job_${operation}`, (params = {}) => bridge.execute_command(`job.${operation}`, params)])));
}
