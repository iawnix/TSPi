"""Resolve, patch, and verify the Pi v1 durable runtime used by TSPi."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "config" / "pi-source.json"
PATCH_ROOT = ROOT / "config" / "pi-patches"
PATCH_NAMES = ("001-workspaces.patch", "002-worker-launch.patch", "003-client-connection.patch", "004-client-lifecycle.patch", "005-client-history.patch", "006-tool-presentation.patch", "007-client-status.patch")
class PiSourceError(RuntimeError): pass

def pin():
    value=json.loads(PIN_PATH.read_text())
    if not isinstance(value,dict) or not isinstance(value.get("commit"),str): raise PiSourceError("invalid Pi source pin")
    return value

def git(source,*args):
    try: return subprocess.run(["git","-C",str(source),*args],check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.strip()
    except (OSError,subprocess.CalledProcessError) as exc: raise PiSourceError(f"cannot inspect Pi source {source}: {exc}") from exc

def verify(source):
    expected=pin()["commit"]
    if git(source,"rev-parse","HEAD") != expected: raise PiSourceError(f"Pi source commit mismatch: expected {expected}")
    required=[
      source/"packages/coding-agent/src/experimental/process.ts",
      source/"packages/coding-agent/src/experimental/session-catalog.ts",
      source/"packages/coding-agent/src/experimental/session-worker.ts",
      source/"packages/coding-agent/src/experimental/session-worker-manager.ts",
      source/"packages/coding-agent/src/experimental/server.ts",
      source/"packages/coding-agent/src/experimental/services/sessions.ts",
      source/"packages/coding-agent/src/experimental/client-tui.ts",
    ]
    if any(not p.is_file() for p in required): raise PiSourceError("Pi source is missing the durable experimental runtime")
    for patch in patches():
        if not patch_check(source, patch, reverse=True):
            raise PiSourceError(f"Pi patch is missing or incompatible: {patch.name}")
    return expected

def patches():
    result = [PATCH_ROOT / name for name in PATCH_NAMES]
    if any(not path.is_file() for path in result):
        raise PiSourceError("missing managed Pi patch files")
    return result

def patch_check(source, patch, *, reverse=False):
    result = subprocess.run(
        ["git", "-C", str(source), "apply", "--check", *(["--reverse"] if reverse else []), str(patch)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.returncode == 0

def apply_patch(source):
    if git(source, "rev-parse", "HEAD") != pin()["commit"]:
        raise PiSourceError("refusing to patch a different Pi source commit")
    pending = []
    # Preflight every independent patch before changing any source file. A
    # complete old patch group is accepted; a partially applied group is not.
    for patch in patches():
        if patch_check(source, patch, reverse=True):
            continue
        if not patch_check(source, patch):
            raise PiSourceError(f"Pi patch is partially applied or incompatible: {patch.name}")
        pending.append(patch)
    for patch in pending:
        try:
            subprocess.run(["git", "-C", str(source), "apply", str(patch)], check=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise PiSourceError(f"failed to apply {patch.name}: {exc}") from exc

def clone(destination):
    p=pin(); destination.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(["git","clone","--no-checkout",p["repository"],str(destination)],check=True)
    git(destination,"fetch","--depth","1","origin",p["commit"]); git(destination,"checkout","--detach",p["commit"])
    apply_patch(destination); verify(destination); return destination

def install(root):
    commit=pin()["commit"]
    try:
        from .app_layout import paths
    except ImportError:
        from app_layout import paths
    destination=paths(Path(root).resolve()).pi_runtime/commit
    if destination.exists():
        if not (destination/"packages/coding-agent/src/experimental/process.ts").is_file(): raise PiSourceError(f"invalid managed Pi source: {destination}")
        apply_patch(destination)
        verify(destination)
    else:
        destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(prefix=".pi-source-",dir=destination.parent) as temp:
            staged=Path(temp)/commit; clone(staged); install_deps(staged); hydrate_model_data(staged); prepare_build(staged); os.replace(staged,destination)
    if not (destination/"node_modules").is_dir(): install_deps(destination)
    hydrate_model_data(destination)
    prepare_build(destination); verify(destination); return destination

def install_deps(source):
    npm=shutil.which("npm")
    if not npm: raise PiSourceError("npm is required")
    subprocess.run([npm,"ci","--ignore-scripts"],cwd=source,check=True,stdout=sys.stderr)

def hydrate_model_data(source):
    """Generate Pi provider model metadata before the offline build.

    The pinned Pi checkout does not commit generated provider data. Its
    offline build validates files such as ``amazon-bedrock.json`` and fails
    without this preparation step.
    """
    data = source / "packages/ai/src/providers/data"
    if (data / "amazon-bedrock.json").is_file():
        return
    npm=shutil.which("npm")
    if not npm: raise PiSourceError("npm is required")
    subprocess.run([npm,"run","hydrate:model-data"],cwd=source,check=True,stdout=sys.stderr)

def prepare_build(source):
    npm=shutil.which("npm")
    if not npm: raise PiSourceError("npm is required")
    if not (source/"packages/chord/dist/index.js").exists() or not (source/"packages/coding-agent/dist/bundle").exists():
        subprocess.run([npm,"run","build:offline"],cwd=source,check=True,stdout=sys.stderr)

def main():
    parser=argparse.ArgumentParser(); group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify",type=Path); group.add_argument("--clone",type=Path); group.add_argument("--install",type=Path)
    args=parser.parse_args()
    try:
        result=verify(args.verify) if args.verify else clone(args.clone) if args.clone else install(args.install)
    except PiSourceError as exc: print(str(exc),file=sys.stderr); return 1
    print(result); return 0
if __name__=="__main__": raise SystemExit(main())
