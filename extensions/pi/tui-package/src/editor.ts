import { CustomEditor } from "@earendil-works/pi-coding-agent";
import type { EditorTheme, TUI } from "@earendil-works/pi-tui";
import type { KeybindingsManager } from "@earendil-works/pi-coding-agent";
import type { Theme } from "@earendil-works/pi-coding-agent";
import {
  applyRoundedEditorBorders,
  cursorOpenFromFgAnsi,
  findBottomBorderIndex,
  restyleEditorCursor,
} from "../../ui/render-utils.ts";
import type { PresentationLayoutContext } from "@earendil-works/pi-coding-agent/experimental/plugin";

export interface TspiEditorMode {
  label: "" | "COMMAND" | "BASH";
  marker: ">" | ":" | "$";
  color: "accent" | "warning" | "bashMode";
}

export function tspiEditorMode(input: string): TspiEditorMode {
  if (input.startsWith("/")) return { label: "COMMAND", marker: ":", color: "warning" };
  if (input.startsWith("!")) return { label: "BASH", marker: "$", color: "bashMode" };
  return { label: "", marker: ">", color: "accent" };
}

export class TspiPresentationEditor extends CustomEditor {
  private readonly palette: Theme;

  constructor(context: PresentationLayoutContext) {
    super(context.tui, context.editorTheme, context.keybindings, { paddingX: 2 });
    this.palette = context.theme;
  }

  override setPaddingX(_padding: number): void {
    super.setPaddingX(2);
  }

  override render(width: number): string[] {
    const input = this.getText();
    const mode = tspiEditorMode(input);
    const rawLines = super.render(width);
    const bottomIndex = findBottomBorderIndex(rawLines);
    for (let index = 1; index < bottomIndex; index += 1) {
      const line = rawLines[index];
      if (!line?.startsWith("  ")) continue;
      const marker = index === 1 ? mode.marker : "│";
      const color = index === 1 ? mode.color : "borderMuted";
      rawLines[index] = `${this.palette.fg(color, marker)} ${line.slice(2)}`;
    }
    const cursorOpen = cursorOpenFromFgAnsi(this.palette.getFgAnsi("accent"));
    const lines = rawLines.map((line) => restyleEditorCursor(line, cursorOpen));
    return applyRoundedEditorBorders(lines, width, (text) => this.borderColor(text), mode.label);
  }
}
