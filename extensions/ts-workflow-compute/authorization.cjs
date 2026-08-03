"use strict";

async function authorizeComputeControl(ctx, request) {
  if (!request || !["submit", "cancel"].includes(request.operation)) {
    throw new Error("compute control authorization accepts only submit or cancel");
  }
  if (!ctx || ctx.hasUI !== true || !ctx.ui || typeof ctx.ui.confirm !== "function") {
    throw new Error(`${request.operation} requires an interactive Pi host confirmation`);
  }
  const approved = await ctx.ui.confirm(
    request.operation === "submit" ? "Submit remote calculation?" : "Cancel remote calculation?",
    confirmationMessage(request),
  );
  if (approved !== true) throw new Error(`${request.operation} was not authorized by the user`);
}

function confirmationMessage(request) {
  const target = isPlainObject(request.executionSummary)
    ? request.executionSummary
    : {
        transport: request.transport || "unknown",
        remote_dir: request.remoteDir || null,
      };
  const details = [
    `Operation: ${request.operation}`,
    `Intent: ${request.intentId}`,
    `Digest: ${request.intentDigest}`,
    `Backend: ${request.backend}`,
    `Node: ${request.nodeId}`,
    `Target: ${JSON.stringify(target)}`,
  ];
  if (request.operation === "cancel") {
    details.push(`Bound job: ${request.jobId || "SSH target-bound job"}`);
  }
  details.push("This approval applies only to this call and cannot be reused by the child agent.");
  return details.join("\n");
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { authorizeComputeControl, confirmationMessage };
