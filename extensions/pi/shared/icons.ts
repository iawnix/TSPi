export type TspiIconStyle = "nerd" | "unicode" | "tspi";

export type TspiIconName =
  | "activity"
  | "cancelled"
  | "completed"
  | "compacting"
  | "context"
  | "coordinating"
  | "cwd"
  | "deepseek"
  | "elapsed"
  | "ephemeral"
  | "failed"
  | "git"
  | "glm"
  | "gpt"
  | "model"
  | "partial"
  | "queued"
  | "remote"
  | "roleCompute"
  | "roleRender"
  | "roleReport"
  | "roleReview"
  | "running"
  | "session"
  | "seeddance"
  | "thinking"
  | "tool"
  | "unknown"
  | "validating"
  | "waiting";

const NERD_ICONS: Readonly<Record<TspiIconName, string>> = Object.freeze({
  activity: "󰐕",
  cancelled: "󰜺",
  completed: "",
  compacting: "",
  context: "󰓅",
  coordinating: "󰒋",
  cwd: "",
  deepseek: "󰈺",
  elapsed: "",
  ephemeral: "",
  failed: "",
  git: "",
  glm: "󰧑",
  gpt: "",
  model: "",
  partial: "",
  queued: "",
  remote: "",
  roleCompute: "",
  roleRender: "",
  roleReport: "",
  roleReview: "",
  running: "",
  session: "◆",
  seeddance: "󰙴",
  thinking: "󰧑",
  tool: "",
  unknown: "",
  validating: "",
  waiting: "",
});

const UNICODE_ICONS: Readonly<Record<TspiIconName, string>> = Object.freeze({
  activity: "π",
  cancelled: "-",
  completed: "✓",
  compacting: "↻",
  context: "◔",
  coordinating: "◎",
  cwd: "▣",
  deepseek: "◈",
  elapsed: "◷",
  ephemeral: "○",
  failed: "×",
  git: "⑂",
  glm: "◎",
  gpt: "✳",
  model: "◇",
  partial: "!",
  queued: "◌",
  remote: "▤",
  roleCompute: "◆",
  roleRender: "▧",
  roleReport: "▤",
  roleReview: "◉",
  running: "●",
  session: "◆",
  seeddance: "✦",
  thinking: "◌",
  tool: "⚒",
  unknown: "?",
  validating: "◆",
  waiting: "◐",
});

// Model icons use the Supplementary Private Use Area so a terminal's primary
// Nerd Font cannot shadow the optional TSPi fallback font.
const TSPI_MODEL_ICONS: Readonly<Partial<Record<TspiIconName, string>>> = Object.freeze({
  model: "\u{F0004}",
  deepseek: "\u{F0000}",
  gpt: "\u{F0001}",
  glm: "\u{F0002}",
  seeddance: "\u{F0003}",
});

export function tspiIconStyle(value = process.env.TSPI_ICON_STYLE): TspiIconStyle {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "unicode") return "unicode";
  if (normalized === "tspi" || normalized === "custom") return "tspi";
  return "nerd";
}

export function tspiIcon(name: TspiIconName, style = tspiIconStyle()): string {
  if (style === "unicode") return UNICODE_ICONS[name];
  if (style === "tspi") return TSPI_MODEL_ICONS[name] || NERD_ICONS[name];
  return NERD_ICONS[name];
}

export function tspiIconLabel(name: TspiIconName, value?: string, style = tspiIconStyle()): string {
  const icon = tspiIcon(name, style);
  return value ? `${icon} ${value}` : icon;
}

export type TspiModelReference = {
  provider?: string;
  id?: string;
};

export type TspiModelIconName = "model" | "deepseek" | "gpt" | "glm" | "seeddance";

/** Resolve a provider/model pair to a stable brand icon, with a generic fallback. */
export function tspiModelIconName(model: TspiModelReference | null | undefined): TspiModelIconName {
  const provider = normalizeModelPart(model?.provider);
  const id = normalizeModelPart(model?.id);

  // Check specific model names before broad OpenAI-compatible provider names.
  if (provider.includes("deepseek") || id.includes("deepseek")) return "deepseek";
  if (
    provider.includes("seedance") ||
    provider.includes("seedream") ||
    provider.includes("bytedance") ||
    provider.includes("volcengine") ||
    provider.includes("doubao") ||
    /(?:^|[-_.])seed(?:ance|ream)(?:[-_.]|\d|$)/u.test(id) ||
    /(?:^|[-_.])doubao[-_.]?seed(?:[-_.]|$)/u.test(id)
  ) {
    return "seeddance";
  }
  if (
    provider.includes("glm") ||
    provider.includes("zhipu") ||
    provider === "zai" ||
    provider.startsWith("zai-") ||
    /(?:^|[-_.:/])glm(?:[-_.:/]|\d|$)/u.test(id)
  ) {
    return "glm";
  }
  if (
    provider.includes("openai") ||
    provider.includes("azure-openai") ||
    provider === "gpt" ||
    provider.startsWith("gpt-") ||
    /(?:^|[-_.:/])gpt(?:[-_.:/]|\d|$)/u.test(id) ||
    /(?:^|[-_.:/])chatgpt(?:[-_.:/]|\d|$)/u.test(id)
  ) {
    return "gpt";
  }
  return "model";
}

export function tspiModelIcon(model: TspiModelReference | null | undefined, style = tspiIconStyle()): string {
  return tspiIcon(tspiModelIconName(model), style);
}

export function tspiModelIconLabel(
  model: TspiModelReference | null | undefined,
  style = tspiIconStyle(),
): string {
  return tspiIconLabel(tspiModelIconName(model), model?.id || "Default model", style);
}

function normalizeModelPart(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}
