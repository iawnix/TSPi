"""Research State's domain-neutral tool admission policy, consumed by the Host."""


def tool_admission(context, liveness, tool):
    name = tool.get("name")
    effect = tool.get("effect")
    args = tool.get("args") or {}
    read = effect == "read"
    checkpoint = name == "research_checkpoint"
    lifecycle = liveness.get("lifecycle")
    def deny(code, reason):
        return {"accepted": False, "code": code, "reason": reason}
    if lifecycle in {"blocked", "user_input_required", "deferred", "terminal"} and not read and not checkpoint:
        return deny("research_user_input_required" if lifecycle == "user_input_required" else "research_lifecycle_blocked",
                    "Research State requires an explicit recovery checkpoint")
    if name == "job_start":
        node_id = args.get("nodeId") or args.get("node_id")
        if node_id and node_id not in liveness.get("ready_node_ids", []):
            return deny("research_node_not_ready", "Node must have a strategy, satisfied dependencies and no blocking state or running Attempt")
    decision_write = effect in {"research_write", "lifecycle_write", "advisory"}
    if lifecycle == "decision_needed" and not liveness.get("execution_ready") and not read and not decision_write:
        return deny("research_decision_required", "Create the Claim/Node and record its research_strategy before execution")
    # Waiting on one Job does not freeze other scoped work or its evidence.
    return {"accepted": True}
