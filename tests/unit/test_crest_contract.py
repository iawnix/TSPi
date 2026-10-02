from pathlib import Path

from tspi_runtime.backends.crest import parse_crest_artifacts


_FRAME = "3\nenergy: -1.0\nO 0 0 0\nH .75 0 .5\nH -.75 0 .5\n"


def _write_artifacts(root: Path, *, best: str = _FRAME, ensemble: str = _FRAME + _FRAME, energies: str = "1 0.0\n2 1.0\n") -> dict[str, Path]:
    values = {
        "crest.out": "Version 3.0.2\nCREST terminated normally.\n",
        "crest_best.xyz": best,
        "crest_conformers.xyz": ensemble,
        "crest.energies": energies,
    }
    paths = {}
    for name, value in values.items():
        path = root / name
        path.write_text(value, encoding="utf-8")
        paths[name] = path
    input_path = root / "input.xyz"
    input_path.write_text(_FRAME, encoding="utf-8")
    paths["input.xyz"] = input_path
    return paths


def test_crest_parser_distinguishes_conformer_and_atom_counts(tmp_path: Path) -> None:
    paths = _write_artifacts(tmp_path)
    parsed = parse_crest_artifacts(paths, input_xyz=paths["input.xyz"])
    summary = parsed["summary"]
    assert summary["conformer_count"] == 2
    assert summary["atom_count"] == 3
    assert summary["best_conformer_count"] == 1
    assert summary["best_atom_count"] == 3
    assert summary["energy_indices_match"] is True
    assert summary["artifacts_complete"] is True


def test_crest_parser_rejects_incomplete_energy_index_table(tmp_path: Path) -> None:
    paths = _write_artifacts(tmp_path, energies="1 0.0\n3 1.0\n")
    try:
        parse_crest_artifacts(paths, input_xyz=paths["input.xyz"])
    except ValueError as error:
        assert "indices are not contiguous" in str(error)
    else:
        raise AssertionError("incomplete CREST energy table was accepted")


def test_crest_parser_marks_best_structure_atom_mismatch_incomplete(tmp_path: Path) -> None:
    wrong_best = "4\nenergy: -1.0\nC 0 0 0\nH .75 0 .5\nH -.75 0 .5\nH 0 0 1\n"
    paths = _write_artifacts(tmp_path, best=wrong_best)
    parsed = parse_crest_artifacts(paths, input_xyz=paths["input.xyz"])
    summary = parsed["summary"]
    assert summary["best_conformer_count"] == 1
    assert summary["best_atom_count"] == 4
    assert summary["best_atom_count_match"] is False
    assert summary["ensemble_atom_count_match"] is True
    assert summary["artifacts_complete"] is False
