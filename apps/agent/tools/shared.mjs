import Type from "../pi/typebox.mjs";
import { createPublicToolContracts } from "./contracts.mjs";
export const TOOL_CONTRACTS = createPublicToolContracts(Type);
export function toolResult(result, text = JSON.stringify(result, null, 2)) {
  return { content: [{ type: "text", text }], details: { result } };
}
