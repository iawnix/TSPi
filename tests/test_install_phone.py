from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.install_from_github import check_phone_protocols, checkout_github
from scripts.install_package import install_launchers, validate_launcher_slots
from scripts.install_phone import activate_phone, check_release, prepare_phone
from tests.test_ts_phone_integration import _copy_launcher


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def phone_repo(tmp_path: Path, monkeypatch):
    source = tmp_path / "upstream"
    source.mkdir()
    package = {"name": "ts-phone", "version": "1.0.0", "type": "module", "scripts": {"build": "node build.mjs"}}
    (source / "package.json").write_text(json.dumps(package))
    (source / "package-lock.json").write_text(json.dumps({"name": "ts-phone", "version": "1.0.0", "lockfileVersion": 3,
        "packages": {"": {"name": "ts-phone", "version": "1.0.0"}}}))
    (source / "services/server").mkdir(parents=True)
    (source / "services/server/package.json").write_text('{"version":"1.0.0","type":"module"}')
    (source / "build.mjs").write_text(
        'import {mkdirSync,writeFileSync} from "node:fs";\n'
        'mkdirSync("services/server/dist",{recursive:true});\n'
        'const code="console.log(JSON.stringify({port:process.env.TS_PHONE_PORT,args:process.argv.slice(2)}));";\n'
        'for(const name of ["index.js","cli.js"])writeFileSync("services/server/dist/"+name,code);\n'
    )
    shutil.copytree(ROOT / "contracts/ts-phone", source / "packages/protocol")
    for command in (["git", "init", "-b", "main"], ["git", "add", "."],
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"]):
        subprocess.run(command, cwd=source, check=True, capture_output=True)
    repo = "https://github.com/tspi-test/phone.git"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{source.as_uri()}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", repo)
    return repo, source


def test_github_branch_and_tag_are_resolved_to_a_commit(tmp_path: Path, phone_repo) -> None:
    repo, source = phone_repo
    subprocess.run(["git", "tag", "v1.0.0"], cwd=source, check=True)
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    for index, ref in enumerate(("main", "v1.0.0", expected)):
        checkout = tmp_path / f"checkout-{index}"
        assert checkout_github(repo, ref, checkout) == expected
        assert (checkout / "package.json").is_file()


def test_source_phone_build_activation_entrypoints_and_upgrade(tmp_path: Path, phone_repo) -> None:
    repo, _ = phone_repo
    root, launcher = _copy_launcher(tmp_path)
    package = launcher.resolve().parent
    shutil.copytree(ROOT / "apps/host", package / "apps/host")
    shutil.copytree(ROOT / "contracts/ts-phone", package / "contracts/ts-phone")
    release = prepare_phone(root, repo, "main")
    assert not (root / "TSPhoneServer").exists()
    assert check_release(release)["repo"] == repo
    result = activate_phone(root, release)
    assert result["commit"] == release.name
    config = root / ".pi/ts-phone/server.env"
    config.write_text("TS_PHONE_PORT=23999\n")
    config.chmod(0o600)
    env = {key: value for key, value in os.environ.items() if not key.startswith("TS_PHONE_") and key != "TS_AGENT_INSTALL_ROOT"}
    for name in ("TSPhoneServer", "TSPhoneCtl"):
        completed = subprocess.run([str(root / name), "--help"], env=env, capture_output=True, text=True, timeout=10)
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {"port": "23999", "args": ["--help"]}
    components = {"agent": {}}
    validate_launcher_slots(root, components)
    installed = install_launchers(root, root / ".pi/packages/tspi", components)
    assert {"TSPhoneServer", "TSPhoneCtl"}.issubset(installed)
    assert prepare_phone(root, repo, "main") == release
    assert config.read_text() == "TS_PHONE_PORT=23999\n"

    # Detect changes before importing a selected server file.
    with (release / "services/server/dist/index.js").open("a") as stream:
        stream.write("\nconsole.log('modified');")
    rejected = subprocess.run([str(root / "TSPhoneServer")], env=env, capture_output=True, text=True, timeout=10)
    assert rejected.returncode == 1 and "failed verification" in rejected.stderr
    assert not rejected.stdout


def test_phone_build_reports_bounded_installation_stages(tmp_path: Path, phone_repo) -> None:
    repo, _ = phone_repo
    messages = []

    release = prepare_phone(tmp_path / "install", repo, "main", progress=messages.append)

    assert release.is_dir()
    assert messages == [
        "Resolving TS Phone revision main",
        "Installing TS Phone dependencies",
        "Building the TS Phone server",
        "Validating the TS Phone server build",
        "Pruning TS Phone build dependencies",
    ]


def test_failed_phone_build_keeps_previous_selection(tmp_path: Path, phone_repo) -> None:
    repo, source = phone_repo
    root = tmp_path / "install"
    release = prepare_phone(root, repo, "main")
    current = root / ".pi/ts-phone/current"
    current.symlink_to(f"releases/{release.name}")
    (source / "build.mjs").write_text("process.exit(1);\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "broken build"],
                   cwd=source, check=True, capture_output=True)
    with pytest.raises(subprocess.CalledProcessError):
        prepare_phone(root, repo, "main")
    assert current.resolve() == release
    assert len(list(release.parent.iterdir())) == 1


def test_incompatible_phone_does_not_replace_selected_release(tmp_path: Path, phone_repo) -> None:
    repo, _ = phone_repo
    root, launcher = _copy_launcher(tmp_path)
    package = launcher.resolve().parent
    shutil.copytree(ROOT / "contracts/ts-phone", package / "contracts/ts-phone")
    release = prepare_phone(root, repo, "main")
    check_phone_protocols(release, package)
    (package / "contracts/ts-phone/versions.json").write_text('{"api":"different"}')
    with pytest.raises(ValueError, match="protocol versions"):
        activate_phone(root, release)
    assert not (root / ".pi/ts-phone/current").exists()
    assert not (root / "TSPhoneServer").exists()


def test_curl_bootstrap_accepts_noninteractive_stdin(tmp_path: Path) -> None:
    source = tmp_path / "bootstrap-source"
    (source / "scripts").mkdir(parents=True)
    (source / "scripts/install_wizard.py").write_text("import json,sys; print(json.dumps(sys.argv[1:]))\n")
    for command in (["git", "init", "-b", "main"], ["git", "add", "."],
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "bootstrap"]):
        subprocess.run(command, cwd=source, check=True, capture_output=True)
    completed = subprocess.run(["bash", "-s", "--", "--non-interactive", "--with-phone"], cwd=tmp_path,
        input=(ROOT / "install.sh").read_text(), env={**os.environ, "TSPI_INSTALL_REPO": str(source), "TSPI_INSTALL_REF": "main"},
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    arguments = json.loads(completed.stdout)
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    assert arguments[arguments.index("--tspi-ref") + 1] == "main"
    assert arguments[arguments.index("--tspi-commit") + 1] == expected
    assert arguments[-2:] == ["--non-interactive", "--with-phone"]


def test_bootstrap_command_line_ref_selects_the_wizard_revision(tmp_path: Path) -> None:
    source = tmp_path / "bootstrap-source"
    (source / "scripts").mkdir(parents=True)
    wizard = source / "scripts/install_wizard.py"
    wizard.write_text("import json,sys; print(json.dumps({'marker':'main','argv':sys.argv[1:]}))\n")
    for command in (["git", "init", "-b", "main"], ["git", "add", "."],
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "main"]):
        subprocess.run(command, cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "switch", "-c", "selected"], cwd=source, check=True, capture_output=True)
    wizard.write_text("import json,sys; print(json.dumps({'marker':'selected','argv':sys.argv[1:]}))\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "selected"],
                   cwd=source, check=True, capture_output=True)
    selected_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()

    completed = subprocess.run(
        ["bash", "-s", "--", "--tspi-repo", str(source), "--tspi-ref", "selected", "--non-interactive"],
        cwd=tmp_path,
        input=(ROOT / "install.sh").read_text(),
        env={**os.environ, "TSPI_INSTALL_REF": "main"},
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["marker"] == "selected"
    assert result["argv"][result["argv"].index("--tspi-ref") + 1] == "selected"
    assert result["argv"][result["argv"].index("--tspi-commit") + 1] == selected_commit


def test_bootstrap_rejects_external_tspi_commit_override(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["bash", "-s", "--", "--tspi-commit", "a" * 40],
        cwd=tmp_path,
        input=(ROOT / "install.sh").read_text(),
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 1
    assert "reserved for the installer bootstrap" in completed.stderr
