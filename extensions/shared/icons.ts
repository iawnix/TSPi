export type TspiIconStyle = "nerd" | "unicode";

export type TspiIconName =
  | "activity"
  | "cancelled"
  | "completed"
  | "compacting"
  | "context"
  | "coordinating"
  | "cwd"
  | "elapsed"
  | "ephemeral"
  | "failed"
  | "git"
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
  elapsed: "",
  ephemeral: "",
  failed: "",
  git: "",
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
  elapsed: "◷",
  ephemeral: "○",
  failed: "×",
  git: "⑂",
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
  thinking: "◌",
  tool: "⚒",
  unknown: "?",
  validating: "◆",
  waiting: "◐",
});

export function tspiIconStyle(value = process.env.TSPI_ICON_STYLE): TspiIconStyle {
  return String(value || "").trim().toLowerCase() === "unicode" ? "unicode" : "nerd";
}

export function tspiIcon(name: TspiIconName, style = tspiIconStyle()): string {
  return (style === "unicode" ? UNICODE_ICONS : NERD_ICONS)[name];
}

export function tspiIconLabel(name: TspiIconName, value?: string, style = tspiIconStyle()): string {
  const icon = tspiIcon(name, style);
  return value ? `${icon} ${value}` : icon;
}
