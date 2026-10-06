import { createCoreTools } from "../pi-native-tools.mjs";
import { createArtifactRuntime, createJobRuntime } from "../job-artifact-runtime.mjs";

/** Package-owned core Harness tools, separated from chemical execution tools. */
export function createServerExtension(factoryOptions = {}) {
  const workspaceRoot = factoryOptions.workspaceRoot || process.cwd();
  return { tools: createCoreTools({
    ...factoryOptions,
    jobRuntime: factoryOptions.jobRuntime || createJobRuntime({ workspaceRoot }),
    artifactRuntime: factoryOptions.artifactRuntime || createArtifactRuntime({ workspaceRoot }),
  }) };
}
