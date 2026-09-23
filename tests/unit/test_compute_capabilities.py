from __future__ import annotations

import pytest

from ts_agent.compute.capabilities import (
    BACKEND_TASK_INPUT_ROLES,
    CapabilityGapError,
    calculation_capabilities,
    resolve_capability,
    resolve_capability_result,
    validate_capability_parameters,
)


def test_capability_catalog_keeps_adapters_separate_from_readiness() -> None:
    catalog = calculation_capabilities()

    assert catalog["schema_version"] == "ts-capability-catalog/1"
    assert catalog["readiness"]["state"] == "not_probed"
    assert "transport readiness" in catalog["readiness"]["meaning"]
    assert set(BACKEND_TASK_INPUT_ROLES) == {
        "gaussian",
        "xtb",
        "crest",
        "ase_neb",
        "pyscf",
    }
    assert all("backend" not in item and "task_type" not in item for item in catalog["capabilities"])


def test_catalog_describes_executor_contracts_without_strategy_routing() -> None:
    catalog = calculation_capabilities()
    capabilities = {item["capability"]: item for item in catalog["capabilities"]}

    assert {
        "gaussian.sp",
        "gaussian.opt",
        "gaussian.freq",
        "gaussian.opt_freq",
        "gaussian.irc",
        "xtb.scan",
        "crest.conformer_search",
        "pyscf.sp",
        "pyscf.opt_freq",
        "pyscf.ts_freq",
    } <= set(capabilities)
    assert capabilities["ase.neb"]["input_roles"] == ["product", "reactant"]
    assert capabilities["ase.neb"]["output_roles"] == [
        "program_output",
        "reaction_path",
        "trajectory",
        "run_summary",
    ]
    assert capabilities["ase.neb"]["parsers"] == ["ase.neb/1"]
    assert capabilities["ase.neb"]["limits"] == {
        "max_images": 32,
        "calculator": "xtb_cli",
        "neb_methods": ["aseneb", "improvedtangent", "eb", "spline", "string"],
        "optimizers": ["FIRE", "BFGS", "LBFGS", "MDMin"],
    }
    assert "qbics.dmecp" not in capabilities
    assert capabilities["gaussian.opt_freq"]["input_roles"] == ["gjf"]
    assert capabilities["gaussian.opt_freq"]["output_roles"] == [
        "program_output",
        "optimized_geometry",
        "frequencies",
    ]
    assert capabilities["pyscf.sp"]["input_roles"] == ["xyz"]
    assert capabilities["pyscf.sp"]["parsers"] == ["pyscf.output/1"]
    assert capabilities["pyscf.sp"]["limits"]["default_xc"] == "CF22D"
    assert all("candidate_strategies" not in item for item in capabilities.values())


def test_capability_effects_advertise_both_local_and_remote_execution() -> None:
    descriptor = resolve_capability("gaussian.opt_freq", "1").public()

    assert set(descriptor["effects"]) == {
        "local_prepare",
        "local_compute",
        "local_parse",
        "remote_compute",
    }
    # The effect declaration describes what the adapter can do; it is not a
    # readiness assertion.  Live transport/scheduler state stays separate.
    assert calculation_capabilities()["readiness"]["state"] == "not_probed"


def test_capability_parameters_are_descriptor_bound() -> None:
    descriptor = resolve_capability("xtb.opt", "1")
    assert validate_capability_parameters(descriptor, {"max_cycles": 7}) == {"max_cycles": 7}
    with pytest.raises(ValueError, match="Additional properties"):
        validate_capability_parameters(descriptor, {"unknown_setting": "invented"})

    neb = resolve_capability("ase.neb", "1")
    assert validate_capability_parameters(
        neb,
        {
            "images": 7,
            "ci_neb": True,
            "ci_fmax": 0.025,
            "neb_method": "improvedtangent",
            "optimizer": "BFGS",
        },
    ) == {
        "images": 7,
        "ci_neb": True,
        "ci_fmax": 0.025,
        "neb_method": "improvedtangent",
        "optimizer": "BFGS",
    }
    with pytest.raises(ValueError, match="should not be valid"):
        validate_capability_parameters(neb, {"climb": True, "ci_neb": True})
    with pytest.raises(ValueError, match="required property"):
        validate_capability_parameters(neb, {"ci_fmax": 0.025})
    with pytest.raises(ValueError, match="less than the minimum"):
        validate_capability_parameters(neb, {"images": 2})
    with pytest.raises(ValueError, match="dependency"):
        validate_capability_parameters(neb, {"solvent": "water"})


def test_unknown_capability_is_a_structured_nonretryable_gap() -> None:
    result = resolve_capability_result("photochemistry.surface_hop", "1")
    assert result == {
        "schema_version": "ts-capability-gap/1",
        "ok": False,
        "status": "rejected",
        "reason": "capability_unavailable",
        "requested": "photochemistry.surface_hop@1",
        "missing_capability": "photochemistry.surface_hop",
        "requested_version": "1",
        "retryable": False,
    }
    with pytest.raises(CapabilityGapError):
        resolve_capability("photochemistry.surface_hop", "1")
