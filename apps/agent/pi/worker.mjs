import { loadPi } from "./source.mjs";
import { createResearchAgentHarness } from "./setup.mjs";

const workerModule = await loadPi("worker");
const { runSessionWorkerWithHarness } = workerModule;

if (workerModule.isDirectInternalProcessEntry?.(import.meta.url) || process.env.PI_SESSION_WORKER_ENTRY === new URL(import.meta.url).pathname) {
  const processModule = await loadPi("process");
  if (processModule.consumeInternalProcessRole() !== "session-worker") throw new Error("ResearchAgent worker requires Pi session-worker role");
  void runSessionWorkerWithHarness(process.argv.slice(2), createResearchAgentHarness).catch((error) => {
    if (process.env.RESEARCH_AGENT_DEBUG === "1") console.error(error?.stack || error);
    process.exit(1);
  });
}
