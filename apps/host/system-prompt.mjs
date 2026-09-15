import { createHash } from "node:crypto";
import { formatSkillsForSystemPrompt } from "@earendil-works/pi-agent-core";
import Type from "typebox";

const SYS_PROMPT_PARAMETERS = Type.Object({}, { additionalProperties: false });

export function createSystemPromptManifest({ native, skills, extensions = [] }) {
  const sections = [promptSection("native", native)];
  const skillSection = skills ? modelVisibleSkillSection(skills) : undefined;
  if (skillSection) sections.push(skillSection);
  for (const extension of extensions) sections.push(promptSection("extension", extension));
  const effective = sections.map((section) => section.text).join("\n\n");
  return Object.freeze({
    schema_version: "tspi-system-prompt/1",
    effective,
    sha256: sha256(effective),
    sections: Object.freeze(sections),
  });
}

function modelVisibleSkillSection(skills) {
  if (!Array.isArray(skills.items)) throw new TypeError("invalid skill system prompt section");
  const visible = skills.items.filter((skill) => !skill.disableModelInvocation);
  const text = formatSkillsForSystemPrompt(visible);
  if (!text) return undefined;
  return promptSection("skill", {
    source: skills.source,
    inputs: visible.map((skill) => skill.filePath),
    text,
  });
}

export function createSystemPromptTool(manifest) {
  assertManifest(manifest);
  return {
    name: "sys_prompt",
    label: "System Prompt",
    description: "Read the effective system prompt and the native, skill, and extension provenance of each section.",
    parameters: SYS_PROMPT_PARAMETERS,
    async execute() {
      return {
        content: [{ type: "text", text: JSON.stringify(manifest, null, 2) }],
        details: { sha256: manifest.sha256, sectionCount: manifest.sections.length },
      };
    },
  };
}

function promptSection(origin, section) {
  if (!section || typeof section.source !== "string" || !section.source || typeof section.text !== "string") {
    throw new TypeError(`invalid ${origin} system prompt section`);
  }
  return Object.freeze({
    origin,
    source: section.source,
    ...(Array.isArray(section.inputs) ? { inputs: Object.freeze([...section.inputs]) } : {}),
    text: section.text,
    sha256: sha256(section.text),
  });
}

function assertManifest(manifest) {
  if (manifest?.schema_version !== "tspi-system-prompt/1" || typeof manifest.effective !== "string") {
    throw new TypeError("sys_prompt requires a TSPi system prompt manifest");
  }
}

function sha256(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}
