export const RESEARCH_KERNEL_PORT_VERSION: "research_state_port_1";
export const RESEARCH_ADMISSION_REQUEST_SCHEMA: "research_admission_request";
export const RESEARCH_ADMISSION_RESULT_SCHEMA: "research_admission_result";

export interface ResearchStatePort {
  readonly protocol_version: "research_state_port_1";
  read_context(): Promise<Record<string, unknown>>;
  read_liveness(): Promise<Record<string, unknown>>;
  admit_workspace(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  apply_change(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  checkpoint(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  turn(request?: Record<string, unknown>): Promise<Record<string, unknown>>;
  close?(): Promise<void>;
}

export function create_research_state_port(implementation: Omit<ResearchStatePort, "protocol_version">): ResearchStatePort;
export function assert_research_admitted(context: Record<string, unknown>): Record<string, unknown>;
