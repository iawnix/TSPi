declare module "@earendil-works/pi-coding-agent/experimental/plugin" {
  import type { Context, ReplicatedState, Service } from "@earendil-works/chord";
  import type { Component, EditorTheme, TUI } from "@earendil-works/pi-tui";
  import type { CustomEditor, KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";

  export interface PresentationLayoutContext {
    readonly tui: TUI;
    readonly theme: Theme;
    readonly editorTheme: EditorTheme;
    readonly keybindings: KeybindingsManager;
    readonly cwd: string;
    requestRender(): void;
  }
  export type PresentationComponentFactory = (context: PresentationLayoutContext) => Component;
  export type PresentationEditorFactory = (context: PresentationLayoutContext) => CustomEditor;
  export interface PresentationToolRenderer {
    renderShell?: "default" | "self";
    renderCall?: (args: any, theme: Theme, context: any) => Component;
    renderResult?: (result: any, options: { expanded: boolean; isPartial: boolean }, theme: Theme, context: any) => Component;
  }
  export type PresentationToolRenderers = Readonly<Record<string, PresentationToolRenderer>>;
  export interface PresentationLayout {
    getContext(): PresentationLayoutContext;
    setHeader(factory: PresentationComponentFactory | undefined): void;
    setFooter(factory: PresentationComponentFactory | undefined): void;
    setEditor(factory: PresentationEditorFactory | undefined): void;
    setToolRenderers(renderers: PresentationToolRenderers): () => void;
    setTitle(title: string): void;
    requestRender(): void;
  }
  export const PresentationLayout: Service<PresentationLayout>;

  export interface PresentationUI {
    select(title: string, items: readonly PresentationSelectItem[], selectedValue: string | undefined, context: Context): Promise<string | undefined>;
    showStatus(message: string, context: Context): void;
  }
  export interface PresentationSelectItem { readonly value: string; readonly label: string; readonly description?: string; }
  export const PresentationUI: Service<PresentationUI>;

  export interface SlashCommandContribution {
    readonly name: string;
    readonly description?: string;
    readonly argumentHint?: string;
    run(args: string, context: Context): unknown;
  }
  export interface SlashCommands {
    replace(command: SlashCommandContribution): () => void;
  }
  export const SlashCommands: Service<SlashCommands>;

  export interface TranscriptState { readonly snapshot: any; readonly event: any; }
  export interface Transcript { readonly state: ReplicatedState<TranscriptState>; }
  export const Transcript: Service<Transcript>;
}
