"use strict";

function nodeControlProperties(Type) {
  return {
    operation: Type.Union([Type.Literal("pause"), Type.Literal("resume")]),
    nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
    rationale: Type.String({ minLength: 1, maxLength: 4000 }),
  };
}

function nodeControlArguments(params) {
  return ["--node-id", params.nodeId, "--operation", params.operation, "--rationale", params.rationale];
}

module.exports = { nodeControlProperties, nodeControlArguments };
