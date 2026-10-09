// Opt-in, bounded context ablation. No research execution tools or messaging tools.
import { parseArgs } from "node:util";
import { mkdtemp, readFile, writeFile, copyFile, rm, mkdir } from "node:fs/promises";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";
import { createDecisionContextInjector } from "../../apps/agent/tools/decision-context.mjs";

const { values } = parseArgs({ options: {
  "agent-dir": { type: "string" }, output: { type: "string" },
  provider: { type: "string" }, model: { type: "string" },
} });
const piRoot = process.env.RESEARCH_AGENT_TEST_PI_RUNTIME_ROOT;
if (!piRoot || !values["agent-dir"] || !values.output) {
  throw new Error("Use the pinned Pi source resolver and supply --agent-dir and --output; optional --provider/--model override configured defaults.");
}
const testRoot = resolve(process.env.RESEARCH_AGENT_TEST_ROOT || "/home/iaw/project/TSPi/local_debug");
const output = resolve(values.output);
if (!output.startsWith(testRoot + "/")) throw new Error("Evaluation output must be under RESEARCH_AGENT_TEST_ROOT");
const temporary = await mkdtemp(join(testRoot, "eval-t003-"));
const record = { schema_version: "t003-context-evaluation/1", kind: "live-context-ablation", runs: [],
  limitations: "Six bounded decisions on synthetic facts; not an end-to-end research benchmark or a statistical comparison of old/new releases." };
try {
  for (const file of ["models.json", "auth.json", "settings.json"]) {
    await copyFile(join(values["agent-dir"], file), join(temporary, file));
  }
  const settings = JSON.parse(await readFile(join(temporary, "settings.json"), "utf8"));
  const { ModelRuntime } = await import(pathToFileURL(join(piRoot, "packages/coding-agent/src/core/model-runtime.ts")));
  const models = await ModelRuntime.create({ modelsPath: join(temporary, "models.json"),
    authPath: join(temporary, "auth.json"), modelsStorePath: join(temporary, "models-store.json"), allowModelNetwork: false });
  const model = models.getModel(values.provider || settings.defaultProvider, values.model || settings.defaultModel);
  if (!model) throw new Error("Configured evaluation model not found");
  record.model = { provider: model.provider, id: model.id };
  const cases = [
    { id: "wrong_failure_and_producer", history: "The compressed summary says current attempt_b failed with QPErr. Cite art_a as its direct evidence.",
      state: { attempts: [{id:"attempt_b",state:"failed",primary_failure:"optimization_limit",direct_evidence_refs:["art_b"]}],
        interpretations:[{id:"interpretation_old",review_state:"superseded",summary:"QPErr diagnosis and art_a attribution were wrong."}] },
      expected: { failure_kind:"optimization_limit", direct_evidence_ref:"art_b" } },
    { id: "unknown_blocks_terminal", history: "The old summary says all calculations finished, so the workspace is ready for terminal.",
      state: { attempts:[{id:"attempt_b",state:"unknown",job_id:"job_b",
        required_action:{tool:"job_reconcile",attempt_id:"attempt_b",reason:"Execution is not confirmed; scientific completion remains blocked."}}],
        issues:[{code:"execution_unknown",refs:["attempt_b"]}] },
      expected: { terminal_allowed:false, next_action:"reconcile" } },
    { id: "goal_and_gate_survive_history", history: "The geometry job succeeded and the report was delivered. The study can be marked completed.",
      state: { goals:[{id:"claim_ts",statement:"Validate a transition structure and reaction connectivity"}],
        gates:[{id:"gate_ts",criteria:[{id:"irc",source_type:"agent_assessment",description:"Reaction connectivity"}],evaluations:[{verdict:"inconclusive"}]}],
        attempts:[{id:"attempt_b",state:"succeeded",collection_state:"complete"}] },
      expected: { terminal_allowed:false, next_action:"validate" } },
  ];
  for (const scenario of cases) {
    for (const injected of [false, true]) {
      const messages = [{role:"user",content:scenario.history,timestamp:1}];
      let request = { messages };
      const snapshots = [];
      if (injected) {
        const snapshot = {schema_version:"research-decision-context/2",context_id:`ctx_${scenario.id}`,revision:2,events:[],...scenario.state};
        const inject = createDecisionContextInjector({sessionId:"evaluation",readModel:async()=>model,
          bridge:{execute_command:async()=>snapshot}, coordinator:{commit_files:async row=>snapshots.push(row.payload)} });
        request = await inject(request, `evaluation_${scenario.id}`, "evaluation");
      }
      const started = Date.now();
      const response = await models.completeSimple(model, {
        systemPrompt: "You are evaluating a research decision. Use current authoritative facts over historical summaries. A successful job or sent report does not prove scientific criteria. Reply with one JSON object only: failure_kind (input_syntax/optimization_limit/unknown), direct_evidence_ref (string or null), terminal_allowed (boolean indicating scientific completion may be claimed), next_action (interpret/reconcile/validate). Do not invent unavailable facts.",
        messages: request.messages,
      }, { maxTokens: 1000, reasoning: "minimal", signal: AbortSignal.timeout(90_000) });
      const text = response.content.filter(c=>c.type === "text").map(c=>c.text).join("\n");
      let decision;
      try { decision = JSON.parse(text.replace(/^```(?:json)?\s*/, "").replace(/\s*```$/, "")); } catch { decision = null; }
      const passed = Object.entries(scenario.expected).every(([key,value]) => decision?.[key] === value);
      const evidenceValid = decision !== null && (decision.direct_evidence_ref === null ||
        scenario.state.attempts?.some(a=>a.direct_evidence_refs?.includes(decision.direct_evidence_ref)) === true);
      record.runs.push({case_id:scenario.id,injected,passed,evidence_valid:evidenceValid,decision,response_text:text,usage:response.usage,
        stop_reason:response.stopReason,elapsed_ms:Date.now()-started,request_messages:request.messages,telemetry:snapshots});
      console.log(`${scenario.id} context=${injected}: ${passed ? "pass" : "fail"}`);
    }
  }
  record.injected_passes = record.runs.filter(r=>r.injected && r.passed).length;
  record.control_passes = record.runs.filter(r=>!r.injected && r.passed).length;
  record.invalid_evidence_decisions = record.runs.filter(r=>r.injected && !r.evidence_valid).length;
  record.ok = record.injected_passes === cases.length && record.invalid_evidence_decisions === 0;
} finally {
  await mkdir(resolve(output, ".."), {recursive:true});
  await writeFile(output, JSON.stringify(record,null,2)+"\n");
  await rm(temporary,{recursive:true,force:true});
}
if (!record.ok) process.exitCode = 1;
