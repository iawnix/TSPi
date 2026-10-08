"""Research State's domain-neutral tool admission policy, consumed by the Host."""
import hashlib


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
        node_id = args.get("node_id")
        work_id = args.get("work_id") or (args.get("metadata") or {}).get("work_id")
        request_id = args.get("request_id") or args.get("job_id")
        attempts = [a for a in context.get("attempts", []) if a.get("node_id") == node_id]
        for attempt in attempts:
            metadata = attempt.get("metadata", {})
            if request_id and metadata.get("job_id") == (args.get("job_id") or "job_" + hashlib.sha256(request_id.encode()).hexdigest()[:48]):
                return {"accepted": True}  # Runtime validates the immutable request and reconciles it.
            if work_id and metadata.get("job_metadata", {}).get("work_id") == work_id:
                return deny("research_work_already_submitted", "This work identity already has an Attempt; collect/reconcile it. Intentional new work needs a new work_id.")
        if node_id and node_id not in liveness.get("eligible_node_ids", liveness.get("ready_node_ids", [])):
            node = next((n for n in context.get("nodes", []) if n.get("id") == node_id), None)
            plans = [p for p in context.get("strategy_plans", []) if p.get("status", "proposed") in {"proposed", "active"}
                     and (p.get("node_id") == node_id or p.get("claim_id") in (node or {}).get("claim_ids", []))]
            nodes = {n.get("id"): n for n in context.get("nodes", [])}
            unmet = [dependency for dependency in (node or {}).get("dependency_ids", [])
                     if nodes.get(dependency, {}).get("state") != "closed" or nodes.get(dependency, {}).get("outcome") != "completed"]
            return deny("research_node_not_ready", f"Node {node_id} is not eligible: state={(node or {}).get('state', 'missing')}; "
                        f"active_strategy={'present' if plans else 'missing'}; unmet_dependencies={unmet}. Read research_read for blocker details; "
                        "satisfy dependencies and record research_strategy before job_start.")
        if any(a.get("state") in {"started", "running", "unknown"} for a in attempts) and not work_id:
            return deny("research_work_identity_required", "Another Attempt is active in this research scope. Use a distinct work_id for independent work, or reconcile the existing Job.")
    preparation = name in {"bash", "write", "edit"} and tool.get("phase") == "prepare"
    decision_write = effect in {"research_write", "lifecycle_write", "advisory"}
    if lifecycle == "decision_needed" and not liveness.get("execution_ready") and not read and not decision_write and not preparation:
        return deny("research_decision_required", "Create the Claim/Node and record its research_strategy before execution")
    # Waiting on one Job does not freeze other scoped work or its evidence.
    return {"accepted": True}
