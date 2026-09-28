import type { SessionMode, WorkspaceMode } from "./session_mode.mjs";

export const TURN_ROUTER_VERSION: "turn_router_1";
export const TURN_PROTOCOLS: Readonly<{
  light: "agent_turn_request";
  research: "research_turn_request";
}>;

export interface TurnRouterMetadata {
  readonly workspace_mode: WorkspaceMode;
  readonly session_mode?: SessionMode;
  readonly admission_state?: string;
  readonly admission_required?: boolean;
  readonly workspace?: Readonly<Record<string, unknown>>;
  readonly session?: Readonly<Record<string, unknown>>;
}

export interface AgentTurnRequest {
  readonly protocol: "agent_turn_request";
  readonly version: 1;
  readonly request_id: string;
  readonly workspace_id: string;
  readonly session_id: string;
  readonly input: string;
  readonly context?: Readonly<Record<string, unknown>>;
}

export interface ResearchTurnRequest {
  readonly protocol: "research_turn_request";
  readonly version: 1;
  readonly request_id: string;
  readonly workspace_id: string;
  readonly operation: string;
  readonly input: Readonly<Record<string, unknown>>;
  readonly context?: Readonly<Record<string, unknown>>;
}

export type RoutedTurnRequest = AgentTurnRequest | ResearchTurnRequest;
export interface TurnRouter {
  readonly protocol_version: "turn_router_1";
  readonly workspace_mode: WorkspaceMode;
  readonly session_mode: SessionMode;
  readonly turn_protocol: RoutedTurnRequest["protocol"];
  route_turn(request: Readonly<Record<string, unknown>>): RoutedTurnRequest;
}

export function resolve_turn_protocol(metadata: TurnRouterMetadata): RoutedTurnRequest["protocol"];
export function create_turn_router(metadata: TurnRouterMetadata): TurnRouter;
export function route_turn(metadata: TurnRouterMetadata, request: Readonly<Record<string, unknown>>): RoutedTurnRequest;
export function create_turn_request(request: Readonly<{
  workspace_mode: WorkspaceMode;
  session_mode?: SessionMode;
  workspace_state?: string | Readonly<Record<string, unknown>>;
  admission_state?: string;
  admission_required?: boolean;
  request_id: string;
  workspace_id: string;
  session_id?: string;
  input?: string | Readonly<Record<string, unknown>>;
  payload?: Readonly<Record<string, unknown>>;
  operation?: string;
}>): RoutedTurnRequest;
