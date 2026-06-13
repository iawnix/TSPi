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
        "v2 node",
        "v2 fields",
        "v2 state",
        "v2 pair",
        "strict-v2",
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
    assert "OpenSSHRemoteExecutor" in text
    assert ("ssh compute-" + "0-30 " + '"') not in text
    assert "subprocess.run(..., shell=False)" in text


def test_mechanism_analysis_sources_define_method_capability_matrix() -> None:
    text = (REFERENCES / "mechanism_analysis_sources.md").read_text(encoding="utf-8")
    for layer in ("reaction_type", "reaction_center", "electronic", "orbital", "energy"):
        assert f"`{layer}`" in text
    for status in ("hypothesis", "supported", "refuted", "ambiguous", "unavailable"):
        assert f"`{status}`" in text
    for method in ("xTB/GFN", "ASE NEB", "Gaussian TS/Freq", "Gaussian IRC", "QBICS dMECP"):
        assert method in text
    assert "--mechanism-analysis" in text
    assert "Do not infer electronic, orbital, or energy descriptors" in text
    assert "not final electronic, orbital, or barrier" in text


def test_primary_docs_link_mechanism_analysis_sources() -> None:
    source_name = "references/mechanism_analysis_sources.md"
    for path in (
        ROOT / "SKILL.md",
        REFERENCES / "mechanism_reflection.md",
        REFERENCES / "candidate_generation.md",
        REFERENCES / "gaussian_validation.md",
        REFERENCES / "qbics_dmecp.md",
    ):
        assert source_name in path.read_text(encoding="utf-8")
