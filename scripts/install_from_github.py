#!/usr/bin/env python3
"""Build and install CoRAgent directly from an immutable GitHub revision."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from ._installation_metadata import write_installation_marker
except ImportError:
    from _installation_metadata import write_installation_marker


FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
PROGRESS_PREFIX = "@@coragent-progress@@"
GIT_RETRY_ATTEMPTS = 3


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "command failed: " + " ".join(command))
    return result.stdout.strip()


def retry_git(command: list[str], *, cwd: Path | None = None) -> str:
    last_error: RuntimeError | None = None
    for attempt in range(1, GIT_RETRY_ATTEMPTS + 1):
        try:
            return run(command, cwd=cwd)
        except RuntimeError as error:
            last_error = error
            if attempt < GIT_RETRY_ATTEMPTS:
                time.sleep(attempt)
    if last_error is None:
        raise RuntimeError("git command failed without diagnostics")
    raise last_error


def validate_ref(ref: str) -> None:
    if not (FULL_SHA.fullmatch(ref) or TAG.fullmatch(ref)) or ref.startswith((".", "/")) or ".." in ref:
        raise ValueError("--ref must be a branch, tag, or full 40-character commit SHA")


def validate_commit(commit: str) -> None:
    if not FULL_SHA.fullmatch(commit):
        raise ValueError("resolved commit must be a full 40-character SHA")


def validate_repo(repo: str) -> None:
    if repo.startswith("git@github.com:") and repo.split(":", 1)[1].strip("/"):
        return
    parsed = urlparse(repo)
    if parsed.scheme not in {"https", "ssh", "git"} or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("--repo must point to github.com")
    if not parsed.path.strip("/"):
        raise ValueError("--repo must include an owner and repository")


def tree_digest(root: Path) -> str:
    # Match release capture: private config, caches and local_debug never
    # contribute bytes to source provenance, even for a local installation.
    try:
        from ._source_capture import inspect_source
    except ImportError:
        from _source_capture import inspect_source
    return "sha256:" + inspect_source(root)[3]


def checkout_github(repo: str, ref: str, destination: Path) -> str:
    validate_repo(repo)
    validate_ref(ref)
    last_error: RuntimeError | ValueError | None = None
    for filtered in (True, False):
        attempts = GIT_RETRY_ATTEMPTS if filtered else 1
        for attempt in range(attempts):
            if destination.is_symlink() or destination.is_file():
                destination.unlink()
            elif destination.exists():
                shutil.rmtree(destination)
            clone = ["git", "clone"]
            if filtered:
                clone.append("--filter=blob:none")
            clone.extend(("--no-checkout", repo, str(destination)))
            try:
                run(clone)
                retry_git(["git", "fetch", "--depth", "1", "origin", ref], cwd=destination)
                run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=destination)
                commit = run(["git", "rev-parse", "HEAD"], cwd=destination)
                if not FULL_SHA.fullmatch(commit):
                    raise ValueError("GitHub checkout did not resolve to a full commit SHA")
                return commit
            except (RuntimeError, ValueError) as error:
                last_error = error
                if destination.is_symlink() or destination.is_file():
                    destination.unlink()
                elif destination.exists():
                    shutil.rmtree(destination)
                if filtered and attempt < attempts - 1:
                    time.sleep(attempt + 1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("GitHub checkout failed")


def install_uninstaller(install_root: Path, source_root: Path) -> Path:
    destination = install_root.expanduser().resolve()
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError(f"installation root must be a physical directory: {destination}")
    else:
        destination.mkdir(mode=0o700, parents=True)
    private = destination / "runtimes/maintenance"
    for directory in (destination / "runtimes", private):
        if directory.exists() or directory.is_symlink():
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError(f"installer control path must be a physical directory: {directory}")
        else:
            directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    uninstaller = destination / "uninstall.sh"
    for source, target, mode in (
        (source_root / "uninstall.sh", uninstaller, 0o755),
        (source_root / "scripts" / "uninstall.py", private / "uninstall.py", 0o700),
        (source_root / "scripts" / "installer.py", private / "installer.py", 0o700),
        (source_root / "scripts" / "uninstall_link_relay.py", private / "uninstall_link_relay.py", 0o700),
        (source_root / "scripts" / "_terminal_ui.py", private / "_terminal_ui.py", 0o600),
        (source_root / "scripts" / "_installation_metadata.py", private / "_installation_metadata.py", 0o600),
        (source_root / "scripts" / "_job_install.py", private / "_job_install.py", 0o600),
        (source_root / "backend/src/research_agent/foundation/layout.py", private / "app_layout.py", 0o600),
    ):
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            temporary.chmod(mode)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    write_installation_marker(destination)
    return uninstaller


def emit_progress(enabled: bool, message: str) -> None:
    if enabled:
        print(f"{PROGRESS_PREFIX}{message}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument("--ref", required=True, help="Branch, tag, or full commit SHA")
    parser.add_argument("--resolved-commit", help=argparse.SUPPRESS)
    parser.add_argument("--source-root", help=argparse.SUPPRESS)
    parser.add_argument("--install-root", required=True)
    parser.add_argument("--without-web", action="store_true", help="Omit the coragent-web component")
    parser.add_argument("--conda")
    parser.add_argument("--conda-root")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow a dirty local source checkout for validation installs.")
    parser.add_argument("--progress", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        validate_ref(args.ref)
        if args.resolved_commit:
            validate_commit(args.resolved_commit)
        validate_repo(args.repo)
        with tempfile.TemporaryDirectory(prefix="coragent-github-") as temp:
            if args.source_root:
                source_root = Path(args.source_root).expanduser()
                if source_root.is_symlink() or not source_root.is_dir():
                    raise ValueError("--source-root must be a physical source directory")
                checkout = source_root.resolve()
                top_level = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=checkout)).resolve()
                if top_level != checkout:
                    raise ValueError("--source-root must be the top level of its Git checkout")
                commit = run(["git", "rev-parse", "--verify", "HEAD"], cwd=checkout)
                validate_commit(commit)
                emit_progress(args.progress, "Using the locked CoRAgent source checkout")
            else:
                checkout = Path(temp) / "coragent"
                progress_message = (
                    "Checking out the locked CoRAgent revision"
                    if args.resolved_commit
                    else "Resolving the selected CoRAgent revision"
                )
                emit_progress(args.progress, progress_message)
                checkout_ref = args.resolved_commit or args.ref
                commit = checkout_github(args.repo, checkout_ref, checkout)
            if args.resolved_commit and commit.lower() != args.resolved_commit.lower():
                raise ValueError(
                    f"locked CoRAgent commit mismatch: expected {args.resolved_commit}, checked out {commit}"
                )
            digest = tree_digest(checkout)
            output = Path(temp) / "package"
            build = [sys.executable, "scripts/build_package.py", "--output-dir", str(output), "--json"]
            if args.without_web:
                build.append("--without-web")
            if args.allow_dirty:
                build.append("--allow-dirty")
            emit_progress(args.progress, "Building the validated CoRAgent package")
            built = json.loads(run(build, cwd=checkout))
            install = [sys.executable, "scripts/install_package.py", "--manifest", built["manifest"], "--archive", built["archive"], "--install-root", args.install_root, "--json"]
            if args.prepare_only:
                install.append('--prepare-only')
            if args.allow_dirty:
                install.append("--allow-dirty")
            if args.conda:
                install.extend(["--conda", args.conda])
            if args.conda_root:
                install.extend(["--conda-root", args.conda_root])
            emit_progress(args.progress, "Installing the local recovery uninstaller")
            uninstaller = (Path(args.install_root) / 'uninstall.sh' if args.prepare_only
                           else install_uninstaller(Path(args.install_root), checkout))
            emit_progress(args.progress, "Preparing the managed runtime and release")
            installed = json.loads(run(install, cwd=checkout))
            provenance = Path(args.install_root).expanduser().resolve() / "var/state/installation/source-provenance.json"
            provenance.parent.mkdir(parents=True, exist_ok=True)
            provenance_data = {"schema_version": "coragent-source-provenance/1", "repo": args.repo, "ref": args.ref, "commit": commit, "tree_digest": digest, "installed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            if not args.prepare_only:
                provenance.write_text(json.dumps(provenance_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = {
                "commit": commit,
                "tree_digest": digest,
                "manifest": built["manifest"],
                "release_id": installed.get("release_id"),
                "package_root": installed.get("package_root"),
                "launchers": installed.get("launchers"),
                "runtime": installed.get("runtime"),
                "provenance": str(provenance),
                "uninstaller": str(uninstaller),
                **({'prepared': installed['prepared'], 'provenance_data': provenance_data} if args.prepare_only else {}),
            }
            emit_progress(args.progress, "Installation artifacts verified")
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
