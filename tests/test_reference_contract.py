from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from transition_state_workflow.config.state_contract import (
    VALID_CLAIM_STATUSES,
    VALID_OUTCOMES,
)


REFERENCES = ROOT / "references"
USER_FACING_DOCS = [ROOT / "SKILL.md", *REFERENCES.glob("*.md")]


def test_reference_inline_state_examples_use_valid_vocab() -> None:
    for path in REFERENCES.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        for field, valid_values in (
            ("claim_status", VALID_CLAIM_STATUSES),
            ("outcome", VALID_OUTCOMES),
        ):
            for match in re.finditer(rf"\b{field}=([A-Za-z0-9_]+)", text):
                value = match.group(1)
                assert value in valid_values, f"{path.name}: invalid {field}={value}"


def test_mechanism_reflection_does_not_reintroduce_legacy_failure_type_list() -> None:
    text = (REFERENCES / "mechanism_reflection.md").read_text(encoding="utf-8")
    legacy_codes = {
        "input_or_environment_error",
        "scf_nonconvergence",
        "wrong_reaction_coordinate",
        "frequency_validation_failed",
        "irc_not_connected",
    }
    assert "## Failure Types" not in text
    for code in legacy_codes:
        assert not re.search(rf"^- `{re.escape(code)}`:", text, flags=re.MULTILINE)


def test_user_facing_docs_avoid_migration_framing() -> None:
    forbidden = (
        "v" + "2 node",
        "v" + "2 fields",
        "v" + "2 state",
        "v" + "2 pair",
        "strict-" + "v" + "2",
        "legacy state",
        "legacy or duplicated",
        "migrated",
    )
    for path in USER_FACING_DOCS:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden:
            assert phrase not in text, f"{path.name}: remove migration framing {phrase!r}"


def test_compute_host_docs_match_remote_executor_quoting_model() -> None:
    text = (REFERENCES / "compute_hosts.md").read_text(encoding="utf-8")
    assert "remote/exec.py" in text
    assert "remote/job_runner.py" in text
    assert "OpenSSHRemoteExecutor" in text
    assert "ts_remote_job.py submit --engine ase-neb" in text
    assert ("ssh compute-" + "0-30 " + '"') not in text
    assert "subprocess.run(..., shell=False)" in text


def test_candidate_generation_docs_expose_remote_ase_neb_adapter() -> None:
    text = (REFERENCES / "candidate_generation.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/ts_remote_job.py submit --engine ase-neb" in text
    assert "nodes/<node>/outputs" in text
    assert "scripts/ts_remote_job.py" in skill
    assert "--engine ase-neb" in skill


def test_mechanism_analysis_sources_define_method_capability_matrix() -> None:
    text = (REFERENCES / "mechanism_analysis_sources.md").read_text(encoding="utf-8")
    for layer in ("reaction_type", "reaction_center", "electronic", "orbital", "energy"):
        assert f"`{layer}`" in text
    for status in ("hypothesis", "supported", "refuted", "ambiguous", "unavailable"):
        assert f"`{status}`" in text
    for method in (
        "xTB/GFN",
        "ASE NEB",
        "Gaussian-External-xTB",
        "Gaussian TS/Freq",
        "Gaussian IRC",
        "QBICS dMECP",
    ):
        assert method in text
    assert "Mechanism-analysis records use these layers" in text
    assert "source" in text
    assert "Do not infer electronic, orbital, or energy descriptors" in text
    assert "not final electronic, orbital, or barrier" in text


def test_primary_docs_link_mechanism_analysis_sources() -> None:
    source_name = "references/mechanism_analysis_sources.md"
    for path in (
        ROOT / "SKILL.md",
        REFERENCES / "backend_selection.md",
        REFERENCES / "refinement_ladder.md",
        REFERENCES / "mechanism_reflection.md",
        REFERENCES / "candidate_generation.md",
        REFERENCES / "gaussian_external_xtb.md",
        REFERENCES / "gaussian_validation.md",
        REFERENCES / "qbics_dmecp.md",
    ):
        assert source_name in path.read_text(encoding="utf-8")


def test_backend_selection_keeps_candidate_generators_out_of_accepted_ts() -> None:
    text = (REFERENCES / "backend_selection.md").read_text(encoding="utf-8")
    assert "No candidate-generation strategy may set `claim_status=accepted_ts`" in text
    for method in (
        "xTB",
        "ASE",
        "NEB",
        "QST",
        "dimer",
        "QBICS dMECP",
        "Gaussian-External-xTB",
    ):
        assert method in text
    gaussian_external = (REFERENCES / "gaussian_external_xtb.md").read_text(encoding="utf-8")
    assert "`accepted_ts_capable=false`" in gaussian_external
    assert "`candidate_only=true`" in gaussian_external


def test_method_selection_separates_search_strategy_from_level_backend() -> None:
    selection = (REFERENCES / "backend_selection.md").read_text(encoding="utf-8")
    candidate = (REFERENCES / "candidate_generation.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    for text in (selection, candidate, skill):
        assert "search strategy first" in text
        assert "level/backend" in text
    assert "xTB, semiempirical methods, Gaussian-External-xTB, and Gaussian-force execution are levels/backends" in selection
    assert "Do not describe\nxTB/GFN, semiempirical methods, Gaussian-External-xTB, or Gaussian-force\nexecution as standalone search strategies." in candidate
    assert "xTB/GFN, semiempirical, Gaussian-External-xTB, Gaussian-force calculator, DFT/Gaussian" in selection


def test_primary_docs_link_low_to_high_refinement_ladder() -> None:
    source_name = "references/refinement_ladder.md"
    for path in (
        ROOT / "SKILL.md",
        REFERENCES / "backend_selection.md",
        REFERENCES / "candidate_generation.md",
        REFERENCES / "gaussian_validation.md",
    ):
        assert source_name in path.read_text(encoding="utf-8")
    ladder = (REFERENCES / "refinement_ladder.md").read_text(encoding="utf-8")
    for phrase in (
        "low-level endpoint/path/candidate",
        "candidate quality check",
        "geometry transfer to target level",
        "high-level TS optimization",
        "connectivity validation",
        "accepted_ts",
    ):
        assert phrase in ladder


def test_docs_do_not_make_optts_or_qst_default_methods() -> None:
    selection = (REFERENCES / "backend_selection.md").read_text(encoding="utf-8")
    candidate = (REFERENCES / "candidate_generation.md").read_text(encoding="utf-8")
    gaussian = (REFERENCES / "gaussian_validation.md").read_text(encoding="utf-8")
    assert "Do not use QST2 merely because a previous `Opt=TS` failed." in selection
    assert "Generally avoid QST3." in selection
    assert "It is not a global default starting point." in selection
    assert "Do not use QST2 merely\nbecause a previous TS optimization failed." in candidate
    assert "Gaussian TS optimization is a refinement or validation step for a specific\ncandidate, not a default search method." in gaussian


def test_user_facing_docs_use_repo_local_script_examples() -> None:
    installed_script_prefix = "/home/iaw/.codex/skills/transition-state-workflow/scripts/"
    for path in USER_FACING_DOCS:
        text = path.read_text(encoding="utf-8")
        assert installed_script_prefix not in text, f"{path.name}: use repo-local scripts/ examples"
