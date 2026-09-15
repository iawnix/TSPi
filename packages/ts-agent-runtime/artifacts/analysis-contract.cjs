"use strict";

const { createHash } = require("node:crypto");

function analysisProperties(Type) {
  return {
    operation: Type.Literal("run"),
    nodeId: Type.String({ pattern: "^node_[1-9][0-9]*$" }),
    capability: Type.String({ minLength: 1, maxLength: 128 }),
    capabilityVersion: Type.String({ minLength: 1, maxLength: 32 }),
    inputArtifacts: Type.Object({}, {
      additionalProperties: Type.Array(Type.String(), { maxItems: 64 }),
      maxProperties: 8,
    }),
    parameters: Type.Object({}, { additionalProperties: true, maxProperties: 16 }),
  };
}

function analysisRequest(params) {
  return {
    schema_version: "ts-analysis-request/1",
    node_id: params.nodeId,
    capability: params.capability,
    capability_version: params.capabilityVersion,
    input_artifacts: params.inputArtifacts,
    parameters: params.parameters,
  };
}

function analysisRequestSummary(params) {
  return {
    capability: params.capability,
    capability_version: params.capabilityVersion,
    input_artifact_ids: Object.values(params.inputArtifacts).flat(),
    submitted_sha256: "sha256:" + createHash("sha256")
      .update(JSON.stringify(analysisRequest(params))).digest("hex"),
  };
}

function validateAnalysisResult(raw, params) {
  if (raw?.schema_version === "ts-capability-gap/1") {
    const error = new Error(`analysis capability unavailable: ${params.capability}@${params.capabilityVersion}`);
    error.code = raw.reason;
    throw error;
  }
  if (!raw || raw.schema_version !== "ts-analysis-result/1" || raw.operation !== "run"
      || raw.capability !== params.capability || raw.capability_version !== params.capabilityVersion
      || raw.node_id !== params.nodeId || raw.analysis_artifact?.owner_node !== params.nodeId) {
    throw new Error("scientific analysis returned an invalid result binding");
  }
}

module.exports = { analysisProperties, analysisRequest, analysisRequestSummary, validateAnalysisResult };
