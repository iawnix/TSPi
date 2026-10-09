"""Pi discovers Skills; scientific execution has an independent declaration."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts._resources import validate_resources

ROOT = Path(__file__).resolve().parents[2]


def test_resources_are_complete_and_match_their_bytes():
    validate_resources(ROOT)
    inventory = json.loads((ROOT / "config/resources.json").read_text())["files"]
    assert "prompts/research-agent.md" in inventory
    for directory in ("skills", "domains", "prompts"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                assert path.relative_to(ROOT).as_posix() in inventory


def test_execution_catalog_uses_its_own_schema_and_resources():
    schema = json.loads((ROOT / "backend/src/research_agent/application/execution_schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    package = json.loads((ROOT / "package.json").read_text())
    assert package["pi"]["extensions"] == []
    for relative in package["researchAgent"]["execution"]:
        catalog = json.loads((ROOT / relative).read_text())
        Draft202012Validator(schema).validate(catalog)
        for executor in catalog["executors"]:
            assert executor["resources"]
            assert not any(path.endswith("SKILL.md") for path in executor["resources"])
