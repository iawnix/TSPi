"""Canonical v2 state contract for TS-search workspaces."""

from __future__ import annotations

WORKSPACE_NODE_SCHEMA = "ts-node-v2"
TREE_SCHEMA = "tssearch-branching-tree-v2"
EVIDENCE_REGISTRY_SCHEMA = "tssearch-evidence-registry-v2"
PATHWAY_MODEL_SCHEMA = "tssearch-pathway-model-v1"
EXPLORER_GRAPH_SCHEMA = "ts-explorer-graph-v2"

REQUIRED_NODE_FIELDS = (
    "schema",
    "node_id",
    "parent_id",
    "stage",
    "operation",
    "lifecycle_state",
    "run_state",
    "claim_status",
    "outcome",
    "outcome_code",
    "claim_level",
)

VALID_LIFECYCLE_STATES = {"prepared", "active", "closed", "superseded", "archived"}
VALID_RUN_STATES = {"not_started", "pending", "running", "parsing", "completed", "stopped", "error", "unknown"}
VALID_CLAIM_STATUSES = {
    "not_evaluated",
    "endpoint_minima_ready",
    "candidate_found",
    "tsfreq_validated",
    "irc_raw_completed",
    "endpoint_connected",
    "irc_connected",
    "accepted_ts",
    "rejected",
    "ambiguous",
}
VALID_OUTCOMES = {
    "none",
    "endpoint_minima_validated",
    "candidate_generated",
    "tsfreq_validated",
    "irc_raw_completed",
    "connectivity_validated",
    "accepted",
    "chemical_failure",
    "numerical_failure",
    "wrong_mode",
    "wrong_endpoint",
    "administrative_stop",
    "parser_refused",
    "superseded",
}
VALID_CLAIM_LEVELS = {"none", "candidate_only", "tsfreq_validated_only", "connectivity_checked", "accepted_ts"}
VALID_EVIDENCE_STATES = {"prepared", "supports", "refutes", "ambiguous", "candidate_found", "administrative", "superseded"}
VALID_BACKTRACK_EVENT_STATES = {"active", "resolved", "superseded"}
MECHANISM_ANALYSIS_LAYERS = ("reaction_type", "reaction_center", "electronic", "orbital", "energy")
MECHANISM_ANALYSIS_STATUSES = {"hypothesis", "supported", "refuted", "ambiguous", "unavailable"}

CLAIM_LEVEL_RANK = {
    "none": 0,
    "candidate_only": 1,
    "tsfreq_validated_only": 2,
    "connectivity_checked": 3,
    "accepted_ts": 4,
}

MAXIMUM_CLAIM_LEVEL_BY_CLAIM_STATUS = {
    "not_evaluated": "none",
    "endpoint_minima_ready": "none",
    "candidate_found": "candidate_only",
    "tsfreq_validated": "tsfreq_validated_only",
    "irc_raw_completed": "tsfreq_validated_only",
    "endpoint_connected": "connectivity_checked",
    "irc_connected": "connectivity_checked",
    "accepted_ts": "accepted_ts",
    "rejected": "none",
}

# claim_level is fully derived from claim_status. It is still written into
# node.json for schema compatibility, but tools must never accept it as input.
DERIVED_CLAIM_LEVEL_BY_CLAIM_STATUS = {
    "ambiguous": "none",
    **MAXIMUM_CLAIM_LEVEL_BY_CLAIM_STATUS,
}

# Default outcome for claim statuses that describe a successful evidence gate.
# Failure-shaped statuses (rejected, ambiguous) have no default: the caller
# must say what specifically went wrong.
DEFAULT_OUTCOME_BY_CLAIM_STATUS = {
    "not_evaluated": "none",
    "endpoint_minima_ready": "endpoint_minima_validated",
    "candidate_found": "candidate_generated",
    "tsfreq_validated": "tsfreq_validated",
    "irc_raw_completed": "irc_raw_completed",
    "endpoint_connected": "connectivity_validated",
    "irc_connected": "connectivity_validated",
    "accepted_ts": "accepted",
}

VALID_OUTCOMES_BY_CLAIM_STATUS = {
    "not_evaluated": {"none", "administrative_stop", "numerical_failure", "parser_refused"},
    "endpoint_minima_ready": {"endpoint_minima_validated"},
    "candidate_found": {"candidate_generated"},
    "tsfreq_validated": {"tsfreq_validated"},
    "irc_raw_completed": {"irc_raw_completed"},
    "endpoint_connected": {"connectivity_validated"},
    "irc_connected": {"connectivity_validated"},
    "accepted_ts": {"accepted"},
    "rejected": {"chemical_failure", "wrong_mode", "wrong_endpoint", "superseded"},
    "ambiguous": {"wrong_mode", "wrong_endpoint", "parser_refused", "superseded"},
}

# Raw claim/outcome/run values stay separate in node.json for auditability. The
# normalizer emits two presentation layers: compact Status[Phase] fields for
# explorer node cards, and node_state/state_line fields for detail/audit views.
NODE_STATE_PRESENTATION = {
    "prepared": {"label": "prepared", "severity": "neutral", "color": "grey"},
    "pending": {"label": "pending", "severity": "progress", "color": "blue"},
    "running": {"label": "running", "severity": "progress", "color": "blue"},
    "parsing": {"label": "parsing", "severity": "progress", "color": "blue"},
    "preflight_complete": {"label": "preflight complete", "severity": "neutral", "color": "grey"},
    "completed_no_claim": {"label": "completed; no TS claim", "severity": "neutral", "color": "grey"},
    "endpoints_ready": {"label": "endpoints ready", "severity": "ok", "color": "cyan"},
    "candidate": {"label": "candidate", "severity": "progress", "color": "accent"},
    "freq_ok": {"label": "freq ok", "severity": "ok", "color": "purple"},
    "irc_raw": {"label": "irc raw", "severity": "progress", "color": "cyan"},
    "endpoint_connected": {"label": "endpoint connected", "severity": "ok", "color": "cyan"},
    "irc_connected": {"label": "irc connected", "severity": "ok", "color": "cyan"},
    "accepted": {"label": "accepted", "severity": "accepted", "color": "green"},
    "ambiguous": {"label": "ambiguous", "severity": "warn", "color": "amber"},
    "rejected": {"label": "rejected", "severity": "fail", "color": "red"},
    "chemical_failure": {"label": "chemical failure", "severity": "fail", "color": "red"},
    "numerical_failure": {"label": "numerical failure", "severity": "warn", "color": "red"},
    "wrong_mode": {"label": "wrong mode", "severity": "fail", "color": "red"},
    "wrong_endpoint": {"label": "wrong endpoint", "severity": "fail", "color": "red"},
    "stopped": {"label": "stopped", "severity": "neutral", "color": "grey"},
    "parser_refused": {"label": "parser refused", "severity": "warn", "color": "red"},
    "superseded": {"label": "superseded", "severity": "neutral", "color": "grey"},
    "error": {"label": "error", "severity": "fail", "color": "red"},
    "unknown": {"label": "unknown", "severity": "warn", "color": "amber"},
}

CARD_STATUS_PRESENTATION = {
    "ready": {"label": "Ready", "severity": "neutral", "color": "grey"},
    "running": {"label": "Running", "severity": "progress", "color": "blue"},
    "success": {"label": "Success", "severity": "ok", "color": "green"},
    "error": {"label": "Error", "severity": "fail", "color": "red"},
    "stopped": {"label": "Stopped", "severity": "neutral", "color": "grey"},
    "unknown": {"label": "Unknown", "severity": "warn", "color": "amber"},
}

CARD_PHASE_PRESENTATION = {
    "preflight": {"label": "Preflight"},
    "endpoint": {"label": "Endpoint"},
    "candidate": {"label": "Candidate"},
    "validation": {"label": "Validation"},
    "pathway": {"label": "Pathway"},
}

# Workspace-level claim_state presentation: same shape as NODE_STATE_PRESENTATION,
# but for the overall pathway/accept state of a workspace. UI reads this verbatim.
WORKSPACE_STATE_PRESENTATION = {
    "accepted_ts": {"label": "accepted", "severity": "accepted", "color": "green"},
    "searching": {"label": "searching", "severity": "progress", "color": "grey"},
    "pathway_hypothesis": {"label": "pathway", "severity": "neutral", "color": "grey"},
    "pathway_partial": {"label": "partial", "severity": "progress", "color": "cyan"},
    "pathway_complete": {"label": "complete", "severity": "accepted", "color": "green"},
    "pathway_ambiguous": {"label": "ambiguous", "severity": "warn", "color": "amber"},
    "pathway_rejected": {"label": "rejected", "severity": "fail", "color": "red"},
}

EVIDENCE_STATE_PRESENTATION = {
    "prepared": {"label": "prepared", "severity": "neutral", "color": "grey"},
    "supports": {"label": "supports", "severity": "ok", "color": "accent"},
    "refutes": {"label": "refutes", "severity": "fail", "color": "red"},
    "ambiguous": {"label": "ambiguous", "severity": "warn", "color": "amber"},
    "candidate_found": {"label": "candidate", "severity": "progress", "color": "accent"},
    "administrative": {"label": "administrative", "severity": "neutral", "color": "grey"},
    "superseded": {"label": "superseded", "severity": "neutral", "color": "grey"},
}

CLAIM_STATUS_TO_NODE_STATE = {
    "endpoint_minima_ready": "endpoints_ready",
    "candidate_found": "candidate",
    "tsfreq_validated": "freq_ok",
    "irc_raw_completed": "irc_raw",
    "endpoint_connected": "endpoint_connected",
    "irc_connected": "irc_connected",
    "accepted_ts": "accepted",
    "rejected": "rejected",
    "ambiguous": "ambiguous",
}

OUTCOME_TO_NODE_STATE = {
    "endpoint_minima_validated": "endpoints_ready",
    "candidate_generated": "candidate",
    "tsfreq_validated": "freq_ok",
    "irc_raw_completed": "irc_raw",
    "connectivity_validated": "endpoint_connected",
    "accepted": "accepted",
    "chemical_failure": "chemical_failure",
    "numerical_failure": "numerical_failure",
    "wrong_mode": "wrong_mode",
    "wrong_endpoint": "wrong_endpoint",
    "administrative_stop": "stopped",
    "parser_refused": "parser_refused",
    "superseded": "superseded",
}


def derive_node_state_key(claim_status: str, outcome: str, run_state: str, stage: str) -> str:
    """Return one user-facing state key from the raw v2 audit fields.

    Successful claim statuses dominate so the more specific UI key wins (e.g.
    ``irc_connected`` instead of the coarser ``connectivity_validated``).
    Failure-shaped statuses (``rejected``/``ambiguous``) defer to the outcome
    code so the UI surfaces *why* the branch failed rather than just that it did.
    """

    if claim_status == "irc_connected":
        return "irc_connected"
    if outcome in OUTCOME_TO_NODE_STATE and outcome != "none":
        return OUTCOME_TO_NODE_STATE[outcome]
    if claim_status in CLAIM_STATUS_TO_NODE_STATE:
        return CLAIM_STATUS_TO_NODE_STATE[claim_status]
    if claim_status == "not_evaluated" and outcome == "none":
        if run_state in {"pending", "running", "parsing"}:
            return run_state
        if run_state == "completed":
            if "preflight" in stage.lower():
                return "preflight_complete"
            return "completed_no_claim"
        if run_state == "not_started":
            return "prepared"
        if run_state == "stopped":
            return "stopped"
        if run_state == "error":
            return "error"
    return "unknown"


def build_node_state(
    *,
    claim_status: str,
    outcome: str,
    outcome_code: str | None,
    run_state: str,
    stage: str,
) -> dict[str, str]:
    """Build the single presentation state emitted to the explorer UI."""

    key = derive_node_state_key(claim_status, outcome, run_state, stage)
    presentation = NODE_STATE_PRESENTATION.get(key, NODE_STATE_PRESENTATION["unknown"])
    line = presentation["label"]
    if outcome_code:
        line = f"{line} / {outcome_code}"
    return {
        "key": key,
        "label": presentation["label"],
        "line": line,
        "severity": presentation["severity"],
        "color": presentation["color"],
    }


def derive_card_phase_key(stage: str, operation: str, claim_status: str) -> str:
    """Return the compact explorer-card phase for one node."""

    stage_text = stage.lower()
    operation_text = operation.lower()
    if claim_status in {"tsfreq_validated", "irc_raw_completed", "endpoint_connected", "irc_connected", "accepted_ts"}:
        return "validation"
    if "pathway" in stage_text:
        return "pathway"
    if any(token in stage_text for token in ("preflight", "mechanism")):
        return "preflight"
    if "endpoint" in stage_text:
        return "endpoint"
    if any(token in stage_text for token in ("candidate", "neb", "scan", "qst", "dimer", "qbics", "dmecp")):
        return "candidate"
    text = f"{stage_text} {operation_text} {claim_status}".lower()
    if any(token in text for token in ("tsfreq", "ts_freq", "ts/freq", "irc", "connectivity", "imaginary")):
        return "validation"
    if any(token in text for token in ("candidate", "neb", "scan", "qst", "dimer", "qbics", "dmecp")):
        return "candidate"
    return "candidate"


def derive_card_status_key(
    *,
    lifecycle_state: str,
    run_state: str,
    claim_status: str,
    outcome: str,
) -> str:
    """Return the compact explorer-card status for one node."""

    if outcome == "administrative_stop" or run_state == "stopped":
        return "stopped"
    if run_state in {"pending", "running", "parsing"}:
        return "running"
    if run_state == "not_started" or lifecycle_state == "prepared":
        return "ready"
    if claim_status in {"rejected", "ambiguous"}:
        return "error"
    if outcome in {"chemical_failure", "numerical_failure", "wrong_mode", "wrong_endpoint", "parser_refused"}:
        return "error"
    if run_state == "error":
        return "error"
    if claim_status in CLAIM_STATUS_TO_NODE_STATE or outcome in OUTCOME_TO_NODE_STATE:
        return "success"
    if run_state == "completed" and claim_status == "not_evaluated" and outcome == "none":
        return "success"
    return "unknown"


def build_node_card_status(
    *,
    lifecycle_state: str,
    run_state: str,
    claim_status: str,
    outcome: str,
    stage: str,
    operation: str,
) -> dict[str, str]:
    """Build the compact Status[Phase] presentation for explorer node cards."""

    status_key = derive_card_status_key(
        lifecycle_state=lifecycle_state,
        run_state=run_state,
        claim_status=claim_status,
        outcome=outcome,
    )
    phase_key = derive_card_phase_key(stage, operation, claim_status)
    status = CARD_STATUS_PRESENTATION.get(status_key, CARD_STATUS_PRESENTATION["unknown"])
    phase = CARD_PHASE_PRESENTATION.get(phase_key, CARD_PHASE_PRESENTATION["candidate"])
    line = f"{status['label']}[{phase['label']}]"
    return {
        "key": f"{status_key}_{phase_key}",
        "status": status_key,
        "phase": phase_key,
        "label": line,
        "line": line,
        "severity": status["severity"],
        "color": status["color"],
    }


def derive_claim_level(claim_status: str) -> str:
    """Return the canonical derived claim level for one claim status."""

    return DERIVED_CLAIM_LEVEL_BY_CLAIM_STATUS.get(claim_status, "none")


def valid_outcomes_for_claim_status(claim_status: str) -> set[str]:
    """Return valid outcome values for one claim status."""

    return set(VALID_OUTCOMES_BY_CLAIM_STATUS.get(claim_status, set()))


NODE_LEGACY_RUNTIME_FIELDS = (
    "status",
    "failure_type",
    "backtrack_target",
    "backtrack_to",
    "children",
    "parent",
    "node_type",
    "tool",
)

TREE_LEGACY_TOP_LEVEL_FIELDS = (
    "schema_version",
    "root",
    "root_node",
    "current_best",
    "status",
    "failure_type",
    "backtrack_target",
    "backtrack_to",
    "accepted_ts",
    "branch_decisions",
    "backtrack_edges",
)

TREE_NODE_FORBIDDEN_RUNTIME_FIELDS = (
    "status",
    "lifecycle_state",
    "run_state",
    "claim_status",
    "outcome",
    "outcome_code",
    "claim_level",
    "failure_type",
    "backtrack_target",
    "backtrack_to",
    "children",
    "parent",
    "node_type",
    "tool",
)


# --- Contract checks -------------------------------------------------------
#
# One source of truth for the rules that say "this looks like a v2 workspace
# file." The normalizer turns every violation into a hard ValueError; the
# validator turns it into a soft Finding. Both call into the same functions
# below so the rule set, codes, and messages never drift.


def _text(value: object) -> str:
    """Strip-and-stringify, with None -> empty string.

    This duplicates ``util.path_utils.clean_string`` byte-for-byte on purpose:
    the ``config`` layer is a zero-import leaf so the contract rules in this
    file can be imported by every other module without creating a cycle. The
    helper is kept private so the duplication is contained.
    """

    return str(value).strip() if value is not None else ""


def check_workspace_contract_violations(
    *,
    manifest: dict,
    tree: dict,
    evidence_registry: dict,
) -> list[tuple[str, str]]:
    """Return ``(code, message)`` pairs for v2 contract violations on root files."""

    violations: list[tuple[str, str]] = []
    if _text(manifest.get("node_schema")) != WORKSPACE_NODE_SCHEMA:
        violations.append(
            ("manifest_node_schema_not_v2", "manifest.json must declare node_schema=ts-node-v2")
        )
    if _text(tree.get("schema")) != TREE_SCHEMA:
        violations.append(
            ("tree_schema_not_v2", "tree.json must declare schema=tssearch-branching-tree-v2")
        )
    if _text(evidence_registry.get("schema")) != EVIDENCE_REGISTRY_SCHEMA:
        violations.append(
            (
                "evidence_registry_schema_not_v2",
                "evidence_registry.json must declare schema=tssearch-evidence-registry-v2",
            )
        )
    legacy = [field for field in TREE_LEGACY_TOP_LEVEL_FIELDS if field in tree]
    if legacy:
        violations.append(
            (
                "legacy_tree_top_level_fields",
                f"tree.json contains non-v2 top-level fields: {', '.join(legacy)}",
            )
        )
    return violations


def check_node_contract_violations(
    node_id: str,
    node_payload: dict,
) -> list[tuple[str, str]]:
    """Return ``(code, message)`` pairs for v2 contract violations on one node."""

    violations: list[tuple[str, str]] = []
    if _text(node_payload.get("schema")) != WORKSPACE_NODE_SCHEMA:
        violations.append(("node_schema_not_v2", "node.json must declare schema=ts-node-v2"))
    missing = [field for field in REQUIRED_NODE_FIELDS if field not in node_payload]
    if missing:
        violations.append(
            ("missing_v2_fields", f"node.json missing required v2 fields: {', '.join(missing)}")
        )
    if "node_id" in node_payload:
        # A present-but-empty ``node_id`` is still wrong: callers expect this
        # check to be the single source for node-id consistency. An absent
        # ``node_id`` field is caught above as ``missing_v2_fields``.
        declared_id = _text(node_payload.get("node_id"))
        if declared_id != node_id:
            violations.append(
                (
                    "node_id_mismatch",
                    f"node.json node_id {declared_id!r} does not match directory/tree id {node_id!r}",
                )
            )
    legacy = [field for field in NODE_LEGACY_RUNTIME_FIELDS if field in node_payload]
    if legacy:
        violations.append(
            (
                "legacy_node_fields",
                f"node.json contains legacy fields not allowed in v2 runtime: {', '.join(legacy)}",
            )
        )
    if "claim_level" in node_payload and "claim_status" in node_payload:
        raw_claim_level = _text(node_payload.get("claim_level"))
        derived_level = derive_claim_level(_text(node_payload.get("claim_status")))
        if raw_claim_level != derived_level:
            violations.append(
                (
                    "claim_level_not_derived",
                    f"claim_level {raw_claim_level!r} disagrees with value derived from claim_status "
                    f"({derived_level!r}); claim_level is a derived field",
                )
            )
    return violations
