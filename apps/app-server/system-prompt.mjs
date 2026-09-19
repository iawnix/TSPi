import { formatSkillsForSystemPrompt } from "@earendil-works/pi-agent-core";
import Type from "./pi-runtime-deps.mjs";
import { createPublicToolContracts } from "../../packages/ts-agent-runtime/host-api/tools.mjs";
import {
  createPromptContributor,
  createSystemPromptManifest as createManifest,
  createSystemPromptTool as createTool,
} from "../../packages/ts-agent-runtime/host-api/system-prompt.mjs";

const SYSTEM_PROMPT_CONTRACT = createPublicToolContracts(Type).systemPrompt;

export function createSystemPromptTool(manifestOrResolver) {
  return createTool(manifestOrResolver, SYSTEM_PROMPT_CONTRACT);
}

export function createSystemPromptManifest({ native, skills, extensions = [] }) {
  const contributors = [promptContributor("native", native)];
  const skillSection = skills ? modelVisibleSkillSection(skills) : undefined;
  if (skillSection) contributors.push(skillSection);
  for (const extension of extensions) contributors.push(promptContributor("extension", extension));
  const effective = contributors.map((contributor) => contributor.text).join("\n\n");
  return createManifest({
    runtime: "native-app-server",
    effective,
    contributors,
    provenanceComplete: true,
  });
}

function modelVisibleSkillSection(skills) {
  if (!Array.isArray(skills.items)) throw new TypeError("invalid skill system prompt section");
  const visible = skills.items.filter((skill) => !skill.disableModelInvocation);
  const text = formatSkillsForSystemPrompt(visible);
  if (!text) return undefined;
  return promptContributor("skill", {
    source: skills.source,
    inputs: visible.map((skill) => skill.filePath),
    text,
  });
}

function promptContributor(origin, section) {
  if (!section || typeof section.source !== "string" || !section.source || typeof section.text !== "string") {
    throw new TypeError(`invalid ${origin} system prompt contributor`);
  }
  return createPromptContributor(origin, {
    source: section.source,
    ...(Array.isArray(section.inputs) ? { inputs: [...section.inputs] } : {}),
    text: section.text,
  });
}
