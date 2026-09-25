import type {
  AgentToolResult,
  AgentToolUpdateCallback,
  ExtensionContext,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";

/** Shared callback types for Pi 0.87.x tool adapters. */
export type PiToolId = string;
export type PiToolSignal = AbortSignal | undefined;
export type PiToolUpdate<D = unknown> = AgentToolUpdateCallback<D> | undefined;
export type PiToolContext = ExtensionContext;
export type PiToolResult<D = unknown> = AgentToolResult<D>;
export type PiToolTheme = Theme;
export type PiToolRenderOptions = ToolRenderResultOptions;
export type PiToolRenderContext<P = Record<string, unknown>, S = unknown> = {
  args: P;
  isError: boolean;
  [key: string]: unknown;
};
