import { isAbsolute, relative, resolve } from "node:path";
import { CURSOR_MARKER, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

const COLUMN_GAP = 3;

export function formatCwd(cwd: string, home = process.env.HOME): string {
  if (!home) return cwd;

  const absoluteCwd = resolve(cwd);
  const absoluteHome = resolve(home);
  if (absoluteCwd === absoluteHome) return "~";

  const fromHome = relative(absoluteHome, absoluteCwd);
  if (fromHome && !fromHome.startsWith("..") && !isAbsolute(fromHome)) {
    return `~/${fromHome}`;
  }
  return cwd;
}

export function formatModelLabel(model: { provider?: string; id?: string } | null | undefined): string {
  if (!model?.id) return "Default model";
  return model.provider ? `${model.provider}/${model.id}` : model.id;
}

export function formatThinkingLabel(level: string): string {
  return level === "off" ? "thinking off" : `${level} thinking`;
}

export function center(text: string, width: number): string {
  if (width <= 0) return "";
  const clipped = truncateToWidth(text, width, "…");
  const padding = Math.max(0, width - visibleWidth(clipped));
  return `${" ".repeat(Math.floor(padding / 2))}${clipped}`;
}

export function padRight(text: string, width: number, ellipsis = ""): string {
  if (width <= 0) return "";
  const clipped = truncateToWidth(text, width, ellipsis);
  return `${clipped}${" ".repeat(Math.max(0, width - visibleWidth(clipped)))}`;
}

export function fitColumns(left: string, right: string, width: number): string {
  if (width <= 0) return "";
  if (!right) return truncateToWidth(left, width, "");

  const rightWidth = visibleWidth(right);
  if (rightWidth + 10 >= width) return truncateToWidth(left, width, "");

  const leftWidth = Math.max(0, width - rightWidth - 1);
  const fittedLeft = truncateToWidth(left, leftWidth, "");
  const gap = " ".repeat(Math.max(1, width - visibleWidth(fittedLeft) - rightWidth));
  return truncateToWidth(`${fittedLeft}${gap}${right}`, width, "");
}

export function headerColumnWidths(
  innerWidth: number,
  minLeftWidth = 32,
  minRightWidth = 19,
  maxRightWidth = 30,
): { leftWidth: number; rightWidth: number; useRightColumn: boolean } {
  if (innerWidth <= 0) return { leftWidth: 0, rightWidth: 0, useRightColumn: false };
  if (innerWidth < minLeftWidth + COLUMN_GAP + minRightWidth) {
    return { leftWidth: innerWidth, rightWidth: 0, useRightColumn: false };
  }

  let rightWidth = Math.min(maxRightWidth, Math.max(minRightWidth, Math.round(innerWidth * 0.27)));
  let leftWidth = innerWidth - COLUMN_GAP - rightWidth;
  if (leftWidth < minLeftWidth) {
    leftWidth = minLeftWidth;
    rightWidth = innerWidth - COLUMN_GAP - leftWidth;
  }
  if (leftWidth <= rightWidth) {
    leftWidth = Math.ceil((innerWidth - COLUMN_GAP) * 0.64);
    rightWidth = innerWidth - COLUMN_GAP - leftWidth;
  }
  if (leftWidth < minLeftWidth || rightWidth < minRightWidth) {
    return { leftWidth: innerWidth, rightWidth: 0, useRightColumn: false };
  }
  return { leftWidth, rightWidth, useRightColumn: true };
}

export function borderLine(
  left: string,
  label: string,
  right: string,
  width: number,
  paint: (text: string) => string,
): string {
  if (width <= 0) return "";
  if (width === 1) return paint("─");

  const innerWidth = width - 2;
  const before = "── ";
  const after = " ──";
  const fixedWidth = visibleWidth(before) + visibleWidth(label) + visibleWidth(after);
  if (!label || fixedWidth > innerWidth) {
    return `${paint(left)}${paint("─".repeat(innerWidth))}${paint(right)}`;
  }
  return `${paint(left)}${paint(before)}${label}${paint(after)}${paint("─".repeat(innerWidth - fixedWidth))}${paint(right)}`;
}

export function boxedLine(content: string, width: number, paint: (text: string) => string): string {
  if (width <= 0) return "";
  if (width === 1) return paint("│");
  return `${paint("│")}${padRight(content, width - 2)}${paint("│")}`;
}

export function twoColumn(
  left: string,
  right: string,
  leftWidth: number,
  rightWidth: number,
  paint: (text: string) => string,
): string {
  return `${padRight(left, leftWidth)} ${paint("│")} ${padRight(right, rightWidth, "…")}`;
}

export function stripAnsi(text: string): string {
  return text
    .replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")
    .replace(/\x1b_[^\x07]*(?:\x07|\x1b\\)/g, "");
}

export function isEditorBorderLine(line: string): boolean {
  const plain = stripAnsi(line);
  if (/^─+$/.test(plain)) return true;
  return /^─*\s*[↑↓]\s+\d+\s+more\s*─*$/.test(plain);
}

export function findBottomBorderIndex(lines: string[]): number {
  for (let index = lines.length - 1; index >= 1; index--) {
    if (isEditorBorderLine(lines[index] || "")) return index;
  }
  return Math.max(0, lines.length - 1);
}

export function roundedBorderLine(
  sourceLine: string,
  width: number,
  kind: "top" | "bottom",
  color: (text: string) => string,
  label = "",
): string {
  if (width <= 0) return "";
  if (width === 1) return color("─");

  const [left, right] = kind === "top" ? (["╭", "╮"] as const) : (["╰", "╯"] as const);
  const scrollMatch = stripAnsi(sourceLine).match(/([↑↓]\s+\d+\s+more)/);
  let body = "─".repeat(Math.max(0, width - 2));
  if (scrollMatch) {
    const scrollLabel = `── ${scrollMatch[1]} `;
    body = `${scrollLabel}${"─".repeat(Math.max(0, width - 2 - visibleWidth(scrollLabel)))}`;
  } else if (kind === "top" && label && visibleWidth(label) + 4 <= width) {
    const topLabel = `─ ${label} `;
    body = `${topLabel}${"─".repeat(Math.max(0, width - 2 - visibleWidth(topLabel)))}`;
  }
  return color(truncateToWidth(`${left}${body}${right}`, width, ""));
}

export function applyRoundedEditorBorders(
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
    const content = padRight(truncateToWidth(result[index] || "", width - 1, ""), width - 1);
    result[index] = `${content}${color("│")}`;
  }
  result[bottomIndex] = roundedBorderLine(result[bottomIndex] || "", width, "bottom", color);
  return result.map((line) => padRight(truncateToWidth(line, width, ""), width));
}

export function cursorOpenFromFgAnsi(fgAnsi: string): string {
  let bgAnsi = fgAnsi.replace(/\x1b\[38;/, "\x1b[48;");
  if (bgAnsi === fgAnsi) {
    bgAnsi = fgAnsi.replace(/\x1b\[(3[0-7])m/, (_match, code: string) => `\x1b[${Number(code) + 10}m`);
  }
  if (bgAnsi === fgAnsi) {
    bgAnsi = fgAnsi.replace(/\x1b\[(9[0-7])m/, (_match, code: string) => `\x1b[${Number(code) + 10}m`);
  }
  return `${bgAnsi}\x1b[38;2;20;22;26m`;
}

export function restyleEditorCursor(line: string, openStyle: string): string {
  const markerIndex = line.indexOf(CURSOR_MARKER);
  if (markerIndex !== -1) {
    const afterMarker = markerIndex + CURSOR_MARKER.length;
    const tail = line.slice(afterMarker);
    const replaced = tail.replace(/\x1b\[7m([^\x1b]*)\x1b\[0m/, `${openStyle}$1\x1b[0m`);
    return `${line.slice(0, afterMarker)}${replaced}`;
  }
  return line.replace(/\x1b\[7m([^\x1b]*)\x1b\[0m/, `${openStyle}$1\x1b[0m`);
}

export { CURSOR_MARKER };
