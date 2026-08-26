import {
  CustomEditor,
  type ExtensionContext,
  type KeybindingsManager,
} from "@earendil-works/pi-coding-agent";
import type { EditorTheme, TUI } from "@earendil-works/pi-tui";
import {
  applyRoundedEditorBorders,
  cursorOpenFromFgAnsi,
  findBottomBorderIndex,
  restyleEditorCursor,
} from "./render-utils.ts";

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

export class TspiEditor extends CustomEditor {
  constructor(
    tui: TUI,
    theme: EditorTheme,
    keybindings: KeybindingsManager,
    private readonly ctx: ExtensionContext,
  ) {
    super(tui, theme, keybindings, { paddingX: 2 });
  }

  override setPaddingX(_padding: number): void {
    super.setPaddingX(2);
  }

  override render(width: number): string[] {
    const theme = this.ctx.ui.theme;
    const input = this.getText();
    const mode = tspiEditorMode(input);
    const rawLines = super.render(width);
    const bottomIndex = findBottomBorderIndex(rawLines);

    for (let index = 1; index < bottomIndex; index++) {
      const line = rawLines[index];
      if (!line?.startsWith("  ")) continue;
      const marker = index === 1 ? mode.marker : "│";
      const color = index === 1 ? mode.color : "borderMuted";
      rawLines[index] = `${theme.fg(color, marker)} ${line.slice(2)}`;
    }

    const cursorOpen = cursorOpenFromFgAnsi(theme.getFgAnsi("accent"));
    const lines = rawLines.map((line) => restyleEditorCursor(line, cursorOpen));
    return applyRoundedEditorBorders(lines, width, (text) => this.borderColor(text), mode.label);
  }
}

export { applyRoundedEditorBorders as applyTspiRoundedEditorBorders } from "./render-utils.ts";
