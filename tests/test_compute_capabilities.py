from __future__ import annotations

from ts_compute.capabilities import BACKEND_TASK_INPUT_ROLES, calculation_capabilities


def test_capability_catalog_keeps_adapter_support_separate_from_readiness() -> None:
    catalog = calculation_capabilities()

    assert catalog["schema_version"] == "ts-compute-capabilities/1"
    assert catalog["readiness"]["state"] == "not_probed"
    assert "ts_remote diagnostics" in catalog["readiness"]["meaning"]
    assert set(BACKEND_TASK_INPUT_ROLES) == {
        "gaussian",
        "xtb",
        "crest",
        "ase_neb",
        "qbics_dmecp",
    }


def test_gaussian_is_an_explicit_candidate_generation_backend() -> None:
    catalog = calculation_capabilities()
    gaussian = next(item for item in catalog["backends"] if item["backend"] == "gaussian")
    tasks = {item["task_type"]: item for item in gaussian["tasks"]}

    assert {"relaxed_scan", "qst", "transition_state_optimization"} <= set(
        tasks["opt"]["candidate_strategies"]
    )
    assert "candidate_ranking" in tasks["sp"]["candidate_strategies"]
    assert tasks["irc"]["candidate_strategies"] == []


def test_low_cost_and_path_backends_remain_candidate_options() -> None:
    catalog = calculation_capabilities()
    tasks = {
        (backend["backend"], task["task_type"]): task
        for backend in catalog["backends"]
        for task in backend["tasks"]
    }

    assert tasks[("xtb", "scan")]["candidate_strategies"] == ["relaxed_scan"]
    assert tasks[("crest", "conformer_search")]["candidate_strategies"] == ["conformer_search"]
    assert tasks[("ase_neb", "neb")]["candidate_strategies"] == ["path_search"]
