/**
 * Public import location for the TSPi-to-Pi session port.
 *
 * The contract is owned by Agent Core. Keeping this forwarding module lets
 * adapter consumers import the boundary without creating a second definition
 * in the Pi integration package.
 */
export {
  PI_SESSION_PORT_VERSION,
  AGENT_SESSION_PORT_VERSION,
  create_pi_session_port,
  create_agent_session_port,
  assert_protocol_id,
} from "../agent-core/ports.mjs";
