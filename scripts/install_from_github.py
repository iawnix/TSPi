#!/usr/bin/env python3
"""Build and install TSPi directly from an immutable GitHub revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "command failed: " + " ".join(command))
    return result.stdout.strip()


def validate_ref(ref: str) -> None:
    if not (FULL_SHA.fullmatch(ref) or TAG.fullmatch(ref)) or ref.startswith((".", "/")) or ".." in ref:
        raise ValueError("--ref must be a branch, tag, or full 40-character commit SHA")


def validate_repo(repo: str) -> None:
    if repo.startswith("git@github.com:") and repo.split(":", 1)[1].strip("/"):
        return
    parsed = urlparse(repo)
    if parsed.scheme not in {"https", "ssh", "git"} or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("--repo must point to github.com")
    if not parsed.path.strip("/"):
        raise ValueError("--repo must include an owner and repository")


def tree_digest(root: Path) -> str:
    entries: list[str] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{path.relative_to(root).as_posix()}\0{digest}")
    return "sha256:" + hashlib.sha256("\n".join(entries).encode()).hexdigest()


def checkout_github(repo: str, ref: str, destination: Path) -> str:
    validate_repo(repo)
    validate_ref(ref)
    run(["git", "clone", "--filter=blob:none", "--no-checkout", repo, str(destination)])
    run(["git", "fetch", "--depth", "1", "origin", ref], cwd=destination)
    run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=destination)
    commit = run(["git", "rev-parse", "HEAD"], cwd=destination)
    if not FULL_SHA.fullmatch(commit):
        raise ValueError("GitHub checkout did not resolve to a full commit SHA")
    return commit


def check_phone_protocols(source: Path, tspi: Path) -> dict[str, str]:
    actual = json.loads((source / "packages/protocol/versions.json").read_text(encoding="utf-8"))
    expected = json.loads((tspi / "contracts/ts-phone/versions.json").read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("TS Phone protocol versions do not match the selected TSPi version")
    for name in ("bridge.schema.json", "events.schema.json", "openapi.yaml"):
        if (source / "packages/protocol" / name).read_bytes() != (tspi / "contracts/ts-phone" / name).read_bytes():
            raise ValueError(f"TS Phone {name} does not match the selected TSPi version")
    return actual


def install_uninstaller(install_root: Path, source_root: Path) -> Path:
    destination = install_root.expanduser().resolve()
    private = destination / ".pi" / "tspi"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    uninstaller = destination / "uninstall.sh"
    shutil.copy2(source_root / "uninstall.sh", uninstaller)
    shutil.copy2(source_root / "scripts" / "uninstall.py", private / "uninstall.py")
    shutil.copy2(source_root / "scripts" / "_terminal_ui.py", private / "_terminal_ui.py")
    uninstaller.chmod(0o755)
    (private / "uninstall.py").chmod(0o700)
    (private / "_terminal_ui.py").chmod(0o600)
    return uninstaller


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument("--ref", required=True, help="Branch, tag, or full commit SHA")
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--with-web", action="store_true", help="Include the ts-web component (default)")
    parser.add_argument("--without-web", action="store_true", help="Omit the ts-web component")
    parser.add_argument("--with-render", action="store_true")
    parser.add_argument("--phone-repo")
    parser.add_argument("--phone-ref")
    parser.add_argument("--phone-server-root", type=Path, help="Prepared Phone server to check before installing TSPi.")
    parser.add_argument("--conda")
    parser.add_argument("--conda-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        validate_ref(args.ref)
        validate_repo(args.repo)
        if args.with_web and args.without_web:
            raise ValueError("--with-web and --without-web are mutually exclusive")
        if bool(args.phone_repo) != bool(args.phone_ref):
            raise ValueError("--phone-repo and --phone-ref must be supplied together")
        if args.phone_repo:
            validate_repo(args.phone_repo)
            validate_ref(args.phone_ref)
        with tempfile.TemporaryDirectory(prefix="tspi-github-") as temp:
            checkout = Path(temp) / "tspi"
            commit = checkout_github(args.repo, args.ref, checkout)
            phone_server = args.phone_server_root or Path(args.install_root).expanduser() / ".pi/ts-phone/current"
            if args.phone_server_root or phone_server.exists():
                if not (checkout / "apps/host/phone-component.mjs").is_file():
                    raise ValueError("Selected TSPi revision does not support Phone source installation; select a newer revision")
                check_phone_protocols(phone_server, checkout)
            digest = tree_digest(checkout)
            output = checkout / "dist" / "package"
            build = [sys.executable, "scripts/build_package.py", "--output-dir", str(output), "--json"]
            if args.without_web:
                build.append("--without-web")
            phone_checkout = None
            phone_commit = None
            if args.phone_repo:
                phone_checkout = Path(temp) / "ts-phone"
                phone_commit = checkout_github(args.phone_repo, args.phone_ref, phone_checkout)
                phone_output = phone_checkout / "dist" / "component"
                phone_result = json.loads(run([sys.executable, "deploy/build-component-release.py", "--output-dir", str(phone_output), "--json"], cwd=phone_checkout))
                build.extend(["--phone-manifest", phone_result["manifest"]])
            built = json.loads(run(build, cwd=checkout))
            install = [sys.executable, "scripts/install_package.py", "--manifest", built["manifest"], "--archive", built["archive"], "--install-root", args.install_root, "--json"]
            if args.with_render:
                install.append("--with-render")
            if args.conda:
                install.extend(["--conda", args.conda])
            if args.conda_root:
                install.extend(["--conda-root", args.conda_root])
            installed = json.loads(run(install, cwd=checkout))
            uninstaller = install_uninstaller(Path(args.install_root), checkout)
            provenance = Path(args.install_root).expanduser().resolve() / ".pi" / "packages" / "tspi" / "source-provenance.json"
            provenance.parent.mkdir(parents=True, exist_ok=True)
            provenance.write_text(json.dumps({"schema_version": "tspi-source-provenance/1", "repo": args.repo, "ref": args.ref, "commit": commit, "tree_digest": digest, "phone_repo": args.phone_repo, "phone_ref": args.phone_ref, "phone_commit": phone_commit, "installed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = {"commit": commit, "tree_digest": digest, "phone_commit": phone_commit, "manifest": built["manifest"], "release_id": installed.get("release_id"), "package_root": installed.get("package_root"), "provenance": str(provenance), "uninstaller": str(uninstaller)}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"installed: {result['release_id'] or 'package'}")
            print(f"commit: {result['commit']}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"GitHub source install failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
