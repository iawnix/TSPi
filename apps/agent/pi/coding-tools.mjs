import { createReadTool, createWriteTool, createEditTool, createBashTool } from "@earendil-works/pi-durable/tools";
import { loadPi } from "./source.mjs";
import { adaptCodingTool } from "./tool-adapter.mjs";

export async function createCodingTools(cwd) {
  const [{ createGrepTool }, { createFindTool }, { createLsTool }, { getToolPath }] = await Promise.all([
    loadPi("grep"), loadPi("find"), loadPi("ls"), loadPi("toolsManager"),
  ]);
  for (const dependency of ["rg", "fd"]) {
    if (!getToolPath(dependency)) throw new Error(`Required coding tool dependency is unavailable: ${dependency}`);
  }
  return [
    ...[createReadTool(), createWriteTool(), createEditTool(), createBashTool()]
      .map(tool => ({ ...tool, executionMode: "sequential" })),
    ...[createGrepTool(cwd), createFindTool(cwd), createLsTool(cwd)].map(adaptCodingTool),
  ];
}
