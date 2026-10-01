import assert from "node:assert/strict";
import test from "node:test";
import { createPublicToolContracts } from "../../packages/ts-agent-runtime/host-api/tools.mjs";
import Type from "../../apps/app-server/pi-runtime-deps.mjs";

test("compute contract contains only Native lifecycle operations", () => {
  const contract = createPublicToolContracts(Type).compute;
  assert.equal(contract.parameters.anyOf ?? contract.parameters.oneOf ?? contract.parameters.type, undefined);
  assert.match(JSON.stringify(contract.parameters), /launch/);
  assert.doesNotMatch(JSON.stringify(contract.parameters), /capability_id/);
  assert.doesNotMatch(JSON.stringify(contract.parameters), /input_artifact_ids/);
});
