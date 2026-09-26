// Live model evaluation, opt-in and isolated. Does not execute external chemistry.
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, relative } from "node:path";
import { fileURLToPath } from "node:url";
import Type from "typebox";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { createStateTool, createAnalyzeTool, createDispatchTool, createChangeTool } from "../../../apps/app-server/pi-native-tools.mjs";
import { createPublicToolAlias } from "../../../packages/ts-agent-runtime/host-api/tools.mjs";

const repository = fileURLToPath(new URL("../../..", import.meta.url));
const [provider, modelId, repetitionsText = "3", outputPath] = process.argv.slice(2);
if (!provider || !modelId || !outputPath) throw new Error("Usage: node tools/test/scenarios/mechanism_live_eval.mjs PROVIDER MODEL REPEATS OUTPUT.json");
const repetitions = Number(repetitionsText);
if (!Number.isInteger(repetitions) || repetitions < 1 || repetitions > 3) throw new Error("REPEATS must be 1..3");
const maxTurns = Number(process.env.TSPI_EVAL_MAX_TURNS || 10);
if (!Number.isInteger(maxTurns) || maxTurns < 1 || maxTurns > 20) throw new Error("TSPI_EVAL_MAX_TURNS must be 1..20");
const runtime = await ModelRuntime.create({ allowModelNetwork: false });
const model = runtime.getModel(provider, modelId);
if (!model || !runtime.hasConfiguredAuth(provider)) throw new Error("Configured model/auth is unavailable");
const scratch = await mkdtemp(join(tmpdir(), "tspi-mechanism-eval-"));
process.env.TSPI_NATIVE_WRITES = "1";
process.env.TSPI_PACKAGE_ROOT = repository;
const skills = (await Promise.all([
  "tspi-mechanism-reasoning", "tspi-ts-candidate-generation", "tspi-ts-validation",
  "tspi-irc", "tspi-energetics",
].map(name => readFile(join(repository, `skills/${name}/SKILL.md`), "utf8")))).join("\n\n");
const tools = [
  [createStateTool(), "research.read"],
  [createAnalyzeTool(), "analysis.run"],
  [createDispatchTool(), "execution.dispatch"],
  [createChangeTool(), "research.change"],
].map(([tool, canonicalName]) => createPublicToolAlias(tool, canonicalName)).concat([{
  name: "read", description: "Read an existing workspace artifact or packaged Skill reference.",
  parameters: Type.Object({ path: Type.String() }, { additionalProperties: false }),
  async execute(id, params, update, ctx) {
    const path = resolve(params.path.startsWith("skills/") ? repository : ctx.cwd, params.path);
    const allowed = [ctx.cwd, join(repository, "skills")].some(root => { const rel = relative(root, path); return rel && !rel.startsWith("..") && !rel.startsWith("/"); });
    if (!allowed) throw new Error("read path is outside evaluation inputs");
    const content = await readFile(path, "utf8");
    if (Buffer.byteLength(content) > 65536) throw new Error("read exceeds 64 KiB; use bounded state");
    return { content: [{ type: "text", text: content }], details: {} };
  },
}]);
const cases = [
  ["definition", "Check this closed reaction CCl.[OH-]>>CO.[Cl-], all component multiplicities 1. Propose atom correspondences and preserve ambiguity; no need to select a mechanism.", ["reaction.parse", "reaction.mapping.generate"]],
  ["existing_ts", "The supplied ts.log is a synthetic candidate output. Assess its stationary-point/mode evidence; for the selected H-H mode use bond [0,1] as the expected changing coordinate. State remaining gaps. Do not rebuild the reaction.", ["gaussian.output.analyze", "vibration.analyze_mode"]],
  ["existing_irc", "Only summarize the supplied irc.log endpoint/completion; do not initiate a TS search or assign a basin without evidence.", ["path.endpoint_summary"]],
  ["ambiguous_mapping", "Inspect mapping.json for the supplied reaction. Report whether a unique correspondence is established. Preserve unresolved choices; do not silently choose a map.", []],
  ["failed_search", "failed.json records a failed optimization. Prepare an independent Gaussian TS optimization input from candidate.xyz, HF/STO-3G, charge 0 multiplicity 1. This is only input preparation, no job launch or TS claim.", ["gaussian.input.build"]],
  ["competing_paths", "Compare initial branching from barrier_a.json and barrier_b.json using elementary TST at the bound conditions. Assume shared equilibrated precursor, irreversible products and no product interconversion. Do not infer general network yields.", ["kinetics.tst", "kinetics.branching"]],
  ["node_management", "The user says to pause further work on the supplied Node, inspect the resulting state, then resume the same Node. Keep scientific records and other Nodes intact.", []],
];
const filter = process.env.TSPI_EVAL_CASES?.split(",");
if (filter?.some(id => !cases.some(row => row[0] === id))) throw new Error("Unknown TSPI_EVAL_CASES case");
const report = { schema_version: "ts-live-capability-evaluation/1", provider, model: modelId, repetitions, max_turns: maxTurns, fixture_kind: "synthetic molecular evidence; no quantum-calculation validation", scratch, runs: [] };
let persistence = Promise.resolve();
await mkdir(resolve(outputPath, ".."), { recursive: true });
const pending = cases.filter(row => !filter || filter.includes(row[0])).flatMap(item => Array.from({length: repetitions}, (_, index) => [...item, index + 1]));
await Promise.all(Array.from({length: 3}, async () => {
while (pending.length) {
  const [caseId, task, expected, repetition] = pending.shift();
  const fixture = JSON.parse(execFileSync(process.env.TS_AGENT_PYTHON || "python3", ["-m", "tools.test.scenarios.mechanism_eval_fixture", join(scratch, `${caseId}-${repetition}`), caseId], { cwd: repository, encoding: "utf8" }));
  process.stdout.write(JSON.stringify({ case: caseId, repetition, status: "started" }) + "\n");
  const messages = [{ role: "user", content: `${task}\nWorkspace inputs: ${JSON.stringify(fixture)}\nUse the existing Node. Inspect capability details as needed; explain conclusions and limitations.`, timestamp: Date.now() }];
  const row = { case: caseId, repetition, calls: [], usage: { input: 0, output: 0, totalTokens: 0 }, tool_argument_bytes: 0, administrative_argument_bytes: 0, errors: 0, final: "", completed: false };
  for (let turn = 0; turn < maxTurns; turn++) {
    let response;
    try {
      response = await runtime.complete(model, { systemPrompt: `You are evaluating TSPi scientific capabilities in an isolated test workspace. Choose only capabilities needed for the stated task. Do not accept a Claim from synthetic evidence. Packaged skills root: ${join(repository, "skills")}\n${skills}`, messages, tools: tools.map(({name, description, parameters}) => ({name, description, parameters})) }, { maxTokens: 2048, signal: AbortSignal.timeout(90000) });
    } catch (error) { row.transport_error = error.name; break; }
    messages.push(response);
    for (const key of Object.keys(row.usage)) row.usage[key] += response.usage?.[key] || 0;
    if (response.stopReason === "error" || response.stopReason === "aborted") { row.transport_error = response.stopReason; break; }
    const calls = response.content.filter(part => part.type === "toolCall");
    if (!calls.length) { row.final = response.content.filter(part => part.type === "text").map(part => part.text).join("\n"); break; }
    for (const call of calls) {
      const record = { name: call.name, arguments: call.arguments };
      row.calls.push(record);
      const size = Buffer.byteLength(JSON.stringify(call.arguments));
      row.tool_argument_bytes += size;
      if (["research.read", "research.change", "execution.dispatch"].includes(call.name)) row.administrative_argument_bytes += size;
      let result, isError = false;
      try {
        const tool = tools.find(tool => tool.name === call.name);
        if (!tool) throw new Error("unsupported tool");
        result = await tool.execute(call.id, call.arguments, undefined, { cwd: fixture.workspace }, undefined, { abortSignal: AbortSignal.timeout(30000) });
      } catch (error) { isError = true; row.errors++; record.error = error.message; result = { content: [{ type: "text", text: error.message }] }; }
      record.isError = isError;
      if (!isError && call.name === "analysis.run") {
        const payload = JSON.parse(result.content[0].text);
        record.result = { verdict: payload.verdict, analysis_artifact: payload.analysis_artifact, output_artifacts: payload.output_artifacts };
      }
      messages.push({ role: "toolResult", toolCallId: call.id, toolName: call.name, content: result.content, isError, timestamp: Date.now() });
    }
  }
  const successful = row.calls.filter(call => !call.isError);
  row.capability_coverage = expected.every(capability => successful.some(call => call.name === "analysis.run" && call.arguments.capability === capability));
  row.completed = row.capability_coverage && !!row.final && !row.transport_error;
  if (caseId === "node_management") row.completed &&= ["pause", "resume"].every(operation => successful.some(call => call.name === "execution.dispatch" && call.arguments.operation === operation && call.arguments.nodeId === fixture.node));
  if (caseId === "ambiguous_mapping") row.completed &&= successful.some(call => call.name === "read" && call.arguments.path.endsWith("mapping.json")) && !successful.some(call => call.arguments?.parameters?.candidate_index !== undefined);
  report.runs.push(row);
  const snapshot = JSON.stringify(report, null, 2) + "\n";
  persistence = persistence.then(() => writeFile(outputPath, snapshot));
  await persistence;
  process.stdout.write(JSON.stringify({ case: caseId, repetition, completed: row.completed, errors: row.errors, usage: row.usage, transport_error: row.transport_error }) + "\n");
  if (row.transport_error) break;
}
}));
report.completed_count = report.runs.filter(row => row.completed).length;
await writeFile(outputPath, JSON.stringify(report, null, 2) + "\n");
