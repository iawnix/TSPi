export interface DevelopmentTestCase {
  id: string;
  description: string;
  selectors: readonly string[];
  timeoutMs: number;
}

const RUNTIME_TEST = "tests/test_pi_runtime_integration.py";

const SUBAGENT_CASES: readonly DevelopmentTestCase[] = [
  {
    id: "subagent-review",
    description: "Run a real Pi review child and verify that it receives no tools.",
    selectors: [`${RUNTIME_TEST}::test_real_pi_review_child_session_has_no_tools`],
    timeoutMs: 90_000,
  },
  {
    id: "subagent-compute",
    description: "Run public compute prepare through the real CLI and verify its canonical result.",
    selectors: [`${RUNTIME_TEST}::test_real_pi_public_compute_prepare_uses_canonical_cli_result`],
    timeoutMs: 120_000,
  },
  {
    id: "subagent-artifacts",
    description: "Run real Pi render and report children with one request-bound tool each.",
    selectors: [
      `${RUNTIME_TEST}::test_real_pi_render_child_session_uses_only_bound_tool`,
      `${RUNTIME_TEST}::test_real_pi_report_child_loads_shared_and_selected_policy_with_bound_tool`,
    ],
    timeoutMs: 150_000,
  },
  {
    id: "subagent-lifecycle",
    description: "Verify public subagent lifecycle events for successful and failed child runs.",
    selectors: [`${RUNTIME_TEST}::test_real_pi_public_subagent_emits_ui_lifecycle_updates`],
    timeoutMs: 120_000,
  },
  {
    id: "subagent-contracts",
    description: "Validate task, result, tool, journal, and UI contracts without external services.",
    selectors: [
      "tests/test_pi_subagent_contract.py",
      "tests/test_pi_subagent_ui.py",
      "tests/test_pi_compute_tools.py",
      "tests/test_pi_artifact_tools.py",
      "tests/test_agent_protocol.py",
      "tests/test_agent_run_journal.py",
    ],
    timeoutMs: 180_000,
  },
];

export const DEVELOPMENT_TEST_CASES: readonly DevelopmentTestCase[] = [
  ...SUBAGENT_CASES,
  {
    id: "subagent-all",
    description: "Run every registered deterministic subagent development test.",
    selectors: SUBAGENT_CASES.flatMap((testCase) => testCase.selectors),
    timeoutMs: 420_000,
  },
  {
    id: "package-inventory",
    description: "Load the production package in real Pi and verify its public tool inventory.",
    selectors: [`${RUNTIME_TEST}::test_real_pi_offline_loads_extensions_and_public_tool_inventory`],
    timeoutMs: 90_000,
  },
  {
    id: "workspace-contracts",
    description: "Validate current decision, node ontology, and workspace consistency contracts.",
    selectors: [
      "tests/test_contracts.py",
      "tests/test_research_node_ontology.py",
      "tests/test_workspace_validator.py",
    ],
    timeoutMs: 180_000,
  },
  {
    id: "mcp-contracts",
    description: "Validate MCP diagnostics, TS job service, and remote lifecycle contracts locally.",
    selectors: [
      "tests/test_mcp_diagnostics.py",
      "tests/test_cluster_mcp_ts_jobs.py",
      "tests/test_remote_job_lifecycle.py",
    ],
    timeoutMs: 240_000,
  },
];

export function findDevelopmentTestCase(id: string): DevelopmentTestCase | undefined {
  return DEVELOPMENT_TEST_CASES.find((testCase) => testCase.id === id);
}
