import { createCoreTools } from "../pi-native-tools.mjs";
import { createExecutionRuntime } from "../execution-runtime.mjs";
import { createEvidenceRuntime } from "../evidence-runtime.mjs";
import { create_python_kernel_bridge } from "../../../packages/research-state-bridge/python_kernel_bridge.mjs";

/** Package-owned core Harness tools, separated from chemical execution tools. */
export function createServerExtension(factoryOptions = {}) {
  const workspaceRoot = factoryOptions.workspaceRoot || process.cwd();
  // Production supplies its session-owned bridge. Standalone extension loaders
  // lazily create the same bridge only when a tool is first invoked.
  let ownedBridge;
  const bridge = factoryOptions.commandBridge || { execute_command(...args) {
    ownedBridge ||= create_python_kernel_bridge({ workspace_root: workspaceRoot });
    return ownedBridge.execute_command(...args);
  } };
  return { tools: createCoreTools({
    ...factoryOptions,
    jobRuntime: factoryOptions.jobRuntime || createExecutionRuntime({ bridge }),
    artifactRuntime: factoryOptions.artifactRuntime || createEvidenceRuntime({ bridge }),
  }) };
}
