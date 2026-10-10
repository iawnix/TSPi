import { loadPi } from "./source.mjs";
import { createCoRAgentHarness } from "./setup.mjs";

const workerModule = await loadPi("worker");
const { runSessionWorkerWithHarness } = workerModule;

if (workerModule.isDirectInternalProcessEntry?.(import.meta.url) || process.env.PI_SESSION_WORKER_ENTRY === new URL(import.meta.url).pathname) {
  const processModule = await loadPi("process");
  if (processModule.consumeInternalProcessRole() !== "session-worker") throw new Error("CoRAgent worker requires Pi session-worker role");
  void runSessionWorkerWithHarness(process.argv.slice(2), createCoRAgentHarness).catch((error) => {
    if (process.env.CORAGENT_DEBUG === "1") console.error(error?.stack || error);
    process.exit(1);
  });
}
