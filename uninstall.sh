#!/usr/bin/env bash
set -Eeuo pipefail

command -v python3 >/dev/null 2>&1 || { printf 'Python 3.11+ is required.\n' >&2; exit 127; }
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
SCRIPT_ROOT=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
fi
for candidate in "${SCRIPT_ROOT}/scripts/installer.py" "${SCRIPT_ROOT}/runtimes/maintenance/installer.py"; do
  if [[ -f "${candidate}" ]]; then
    if [[ ! -t 0 ]] && { true </dev/tty; } 2>/dev/null; then
      exec python3 -B "${candidate}" uninstall "$@" </dev/tty
    fi
    exec python3 -B "${candidate}" uninstall "$@"
  fi
done

# Standalone recovery: obtain the dispatcher when the local installation is missing.
command -v git >/dev/null 2>&1 || { printf 'Git is required for recovery.\n' >&2; exit 127; }
bootstrap_root="$(mktemp -d "${TMPDIR:-/tmp}/research-agent-bootstrap.XXXXXX")"
trap 'rm -rf -- "${bootstrap_root}"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
git clone --quiet --depth 1 --no-checkout -- "${RESEARCH_AGENT_INSTALL_REPO:-https://github.com/iawnix/TSPi.git}" "${bootstrap_root}/source"
git -C "${bootstrap_root}/source" fetch --quiet --depth 1 origin "${RESEARCH_AGENT_INSTALL_REF:-main}"
git -C "${bootstrap_root}/source" checkout --quiet --detach FETCH_HEAD
python3 -B "${bootstrap_root}/source/scripts/installer.py" uninstall "$@"
