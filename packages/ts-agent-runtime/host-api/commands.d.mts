export type CommandId =
  | "research.map"
  | "research.summary"
  | "research.detail"
  | "research.locate"
  | "research.validate"
  | "research.operations"
  | "research.continuation"
  | "research.change"
  | "compute.environments"
  | "compute.environment"
  | "compute.capabilities"
  | "compute.artifacts"
  | "compute.runs";

export interface CommandInvocation {
  readonly command: CommandId;
  readonly params: Readonly<Record<string, unknown>>;
}

export interface CommandTransportInvocation extends CommandInvocation {
  readonly root: string;
  readonly signal?: AbortSignal;
}

export const COMMAND_DEFINITIONS: Readonly<Record<CommandId, {
  readonly id: CommandId;
  readonly domain: "research" | "compute";
  readonly effect: "read" | "write";
  readonly required: readonly string[];
}>>;
export const COMMAND_IDS: readonly CommandId[];
export const SLASH_COMMAND_DEFINITIONS: Readonly<Record<string, {
  readonly name: string;
  readonly description: string;
  readonly usage: string;
  readonly completions: readonly string[];
}>>;
export const SLASH_COMMAND_NAMES: readonly string[];

export function createCommandService(transport: {
  execute(invocation: CommandTransportInvocation): Promise<unknown>;
}): {
  execute(command: CommandId, root: string, params?: Record<string, unknown>, signal?: AbortSignal): Promise<any>;
};
export function validateCommandInvocation(command: string, params?: Record<string, unknown>): CommandInvocation;
export function commandArguments(command: string, params?: Record<string, unknown>): string[];
export function parseSlashCommand(name: string, input?: string): CommandInvocation | {
  readonly command: "client.debug.prompt";
  readonly params: Readonly<Record<string, unknown>>;
};
export function slashCompletions(name: string, prefix?: string): Array<{
  value: string;
  label: string;
}> | null;
