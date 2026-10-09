// Compile-only consumer examples. These calls are never executed.
import { createCommandService, type CommandId, type CommandResults } from "../../apps/agent/tools/commands.mjs";
import type { RuntimeBridge } from "../../apps/agent/bridge/client.mjs";

type Assert<T extends true> = T;
type SameKeys = Assert<keyof CommandResults extends CommandId ? CommandId extends keyof CommandResults ? true : false : false>;

export async function checkCommandResultTypes(bridge: RuntimeBridge) {
  const service = createCommandService({ execute: async () => ({}) });
  const material = await service.execute("artifact.create", "/fixture", { content: "fixture" });
  const bytes: number = material.size_bytes;
  // @ts-expect-error Artifact byte length cannot be used as text.
  const wrongBytes: string = material.size_bytes;
  const created = await bridge.execute_command("research.create", { goal: "fixture" });
  const revision: number = created.node.revision;
  // @ts-expect-error Research creation does not return a Job receipt.
  created.job_id;
  const read = await bridge.execute_command("research.read");
  if (read.schema_version === "research-snapshot/2") {
    const sequence: number = read.sequence;
    void sequence;
  } else {
    const offset: number = read.offset;
    void offset;
  }
  const start = await bridge.execute_command("job.start", { command: ["/bin/true"] });
  if ("submitted_at" in start) {
    const platform: string = start.platform;
    void platform;
  }
  // @ts-expect-error Duplicate and uncertain dispatch replies have no submitted_at.
  start.submitted_at;
  // @ts-expect-error An unknown command has no declared response contract.
  await bridge.execute_command("research.unknown");
  return { bytes, wrongBytes, revision };
}
