import { loadPi } from "./source.mjs";
import Type from "./typebox.mjs";
import { createPublicToolContracts } from "../tools/contracts.mjs";
import {
  createPromptContributor,
  createSystemPromptManifest as createManifest,
  createSystemPromptTool as createTool,
} from "./prompt-manifest.mjs";

const SYSTEM_PROMPT_CONTRACT = createPublicToolContracts(Type).systemPrompt;
const { formatSkillsForPrompt } = await loadPi("skills");

export function createSystemPromptTool(manifestOrResolver) {
  return createTool(manifestOrResolver, SYSTEM_PROMPT_CONTRACT);
}

export function createSystemPromptManifest({ native, skills }) {
  const contributors = [promptContributor("native", native)];
  const skillSection = skills ? modelVisibleSkillSection(skills) : undefined;
  if (skillSection) contributors.push(skillSection);
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
  const text = formatSkillsForPrompt(visible);
  if (!text) return undefined;
  return promptContributor("skill", {
    source: skills.source,
    inputs: visible.map((skill) => skill.filePath),
    text,
    metadata: {
      schema_version: "research-agent-skill-manifest/1",
      skills: visible.map((skill) => ({
        name: skill.name,
        description: skill.description,
        location: skill.filePath,
        digest: typeof skill.digest === "string" ? skill.digest : null,
        provenance_schema: skill.provenance_schema || "research-agent-skill-provenance/1",
      })),
    },
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
    ...(section.metadata && typeof section.metadata === "object" ? { metadata: section.metadata } : {}),
  });
}
