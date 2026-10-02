/**
 * Public import location for the shared Agent Runtime Port.
 *
 * The contract is owned by Research Agent Core. Keeping this forwarding module
 * lets adapter consumers import the boundary without creating a second port
 * definition in the Pi package.
 */
export {
  AGENT_RUNTIME_PORT_VERSION,
  AGENT_SESSION_PORT_VERSION,
  create_agent_runtime_port,
  create_agent_session_port,
  assert_protocol_id,
} from "../agent-core/ports.mjs";
