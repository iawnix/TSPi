from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHEMICAL_SKILLS = ROOT / "domains" / "chemical" / "skills"


def test_chemical_execution_skills_use_generic_job_runtime() -> None:
    files = [
        CHEMICAL_SKILLS / "cf22d" / "SKILL.md",
        CHEMICAL_SKILLS / "cf22d" / "SKILL.zh-CN.md",
        CHEMICAL_SKILLS / "xtb" / "SKILL.md",
        CHEMICAL_SKILLS / "xtb" / "SKILL.zh-CN.md",
        CHEMICAL_SKILLS / "gaussian" / "SKILL.md",
        CHEMICAL_SKILLS / "gaussian" / "SKILL.zh-CN.md",
    ]
    forbidden = (
        "no PySCF/CF22D workflow is registered",
        "没有注册 PySCF/CF22D workflow",
        "registered xTB capabilities",
        "已注册的 xTB workflow",
        "live Native catalog is authoritative",
        "实时 Native catalog 中的 `gaussian@1`",
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "job_start" in text, path
        assert not any(value in text for value in forbidden), path


def test_job_runtime_contract_accepts_argv_without_scientific_registry() -> None:
    text = (ROOT / "skills/research-workflow/references/tools.md").read_text(
        encoding="utf-8"
    )
    assert "argv command" in text
    assert "No research object is required" in text
