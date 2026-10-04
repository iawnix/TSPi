import Type from "./pi-runtime-deps.mjs";
import { createPublicToolContracts } from "../../packages/agent-runtime/host-api/tools.mjs";
import {
  createPromptContributor,
  createSystemPromptManifest as createManifest,
  createSystemPromptTool as createTool,
} from "../../packages/agent-runtime/host-api/system-prompt.mjs";

const SYSTEM_PROMPT_CONTRACT = createPublicToolContracts(Type).systemPrompt;
const CORE_SKILL_NAMES = new Set(["orchestration", "research-state"]);

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
  const text = visible.length === 0 ? "" : [
    "<available_skills>",
    ...visible.map((skill) => `  <skill><name>${escapeXml(skill.name)}</name><description>${escapeXml(skill.description)}</description><location>${escapeXml(skill.filePath)}</location></skill>`),
    "</available_skills>",
  ].join("\n");
  if (!text) return undefined;
  return promptContributor("skill", {
    source: skills.source,
    inputs: visible.map((skill) => skill.filePath),
    text,
    metadata: {
      schema_version: "tspi-skill-manifest/1",
      skills: visible.map((skill) => ({
        name: skill.name,
        description: skill.description,
        location: skill.filePath,
        digest: typeof skill.digest === "string" ? skill.digest : null,
        provenance_schema: skill.provenance_schema || "tspi-skill-provenance/1",
        scope: CORE_SKILL_NAMES.has(skill.name) ? "system" : "extension",
        always_visible: CORE_SKILL_NAMES.has(skill.name),
      })),
    },
  });
}

function escapeXml(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

function promptContributor(origin, section) {
  if (!section || typeof section.source !== "string" || !section.source || typeof section.text !== "string") {
    throw new TypeError(`invalid ${origin} system prompt contributor`);
  }
  return createPromptContributor(origin, {
    source: section.source,
    ...(Array.isArray(section.inputs) ? { inputs: [...section.inputs] } : {}),
    text: section.text,
    ...(section.metadata && typeof section.metadata === "object" ? { metadata: section.metadata } : {}),
  });
}
