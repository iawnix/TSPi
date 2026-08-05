import { CustomEditor, type KeybindingsManager } from "@earendil-works/pi-coding-agent";
import {
  truncateToWidth,
  visibleWidth,
  type EditorTheme,
  type TUI,
} from "@earendil-works/pi-tui";

export class TspiEditor extends CustomEditor {
  constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsManager) {
    super(tui, theme, keybindings, { paddingX: 2 });
  }

  override setPaddingX(_padding: number): void {
    super.setPaddingX(2);
  }

  override render(width: number): string[] {
    const input = this.getText();
    const label = input.startsWith("/") ? "COMMAND" : input.startsWith("!") ? "SHELL" : "";
    return applyTspiRoundedEditorBorders(
      super.render(width),
      width,
      (text) => this.borderColor(text),
      label,
    );
  }
}

export function applyTspiRoundedEditorBorders(
  lines: string[],
  width: number,
  color: (text: string) => string,
  label = "",
): string[] {
  if (lines.length === 0 || width < 4) return lines;

  const result = lines.slice();
  const bottomIndex = findBottomBorderIndex(result);
  result[0] = roundedBorderLine(result[0] || "", width, "top", color, label);
  for (let index = 1; index < bottomIndex; index++) {
    const content = padRight(truncateToWidth(result[index] || "", width - 2, ""), width - 2);
    result[index] = `${color("│")}${content}${color("│")}`;
  }
  result[bottomIndex] = roundedBorderLine(result[bottomIndex] || "", width, "bottom", color);
  return result.map((line) => padRight(truncateToWidth(line, width, ""), width));
}

function roundedBorderLine(
  sourceLine: string,
  width: number,
  kind: "top" | "bottom",
  color: (text: string) => string,
  label = "",
): string {
  const [left, right] = kind === "top" ? (["╭", "╮"] as const) : (["╰", "╯"] as const);
  const scrollMatch = stripAnsi(sourceLine).match(/([↑↓]\s+\d+\s+more)/);
  let body = "─".repeat(width - 2);

  if (scrollMatch) {
    const scrollLabel = `── ${scrollMatch[1]} `;
    body = `${scrollLabel}${"─".repeat(Math.max(0, width - 2 - visibleWidth(scrollLabel)))}`;
  } else if (kind === "top" && label && visibleWidth(label) + 4 <= width) {
    const topLabel = `─ ${label} `;
    body = `${topLabel}${"─".repeat(Math.max(0, width - 2 - visibleWidth(topLabel)))}`;
  }

  return color(truncateToWidth(`${left}${body}${right}`, width, ""));
}

function findBottomBorderIndex(lines: string[]): number {
  for (let index = lines.length - 1; index >= 1; index--) {
    const plain = stripAnsi(lines[index] || "");
    if (/^─+$/.test(plain) || /^─*\s*[↑↓]\s+\d+\s+more\s*─*$/.test(plain)) return index;
  }
  return Math.max(0, lines.length - 1);
}

function stripAnsi(value: string): string {
  return value
    .replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")
    .replace(/\x1b_[^\x07]*(?:\x07|\x1b\\)/g, "");
}

function padRight(value: string, width: number): string {
  const clipped = truncateToWidth(value, width, "");
  return `${clipped}${" ".repeat(Math.max(0, width - visibleWidth(clipped)))}`;
}
