#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="${TSPI_INSTALL_REPO:-https://github.com/iawnix/TSPi.git}"
readonly REPO_REF="${TSPI_INSTALL_REF:-main}"
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
fi
readonly SCRIPT_DIR

if [[ -f "${SCRIPT_DIR}/scripts/install_wizard.py" && -f "${SCRIPT_DIR}/package.json" ]]; then
  exec python3 "${SCRIPT_DIR}/scripts/install_wizard.py" "$@"
fi

command -v git >/dev/null 2>&1 || { echo "TSPi installer requires Git." >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "TSPi installer requires Python 3." >&2; exit 127; }

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tspi-installer.XXXXXX")"
cleanup() { rm -rf -- "${TEMP_ROOT}"; }
trap cleanup EXIT INT TERM

git clone --filter=blob:none --no-checkout "${REPO_URL}" "${TEMP_ROOT}/TSPi"
git -C "${TEMP_ROOT}/TSPi" fetch --depth 1 origin "${REPO_REF}"
git -C "${TEMP_ROOT}/TSPi" checkout --detach FETCH_HEAD
wizard=(python3 "${TEMP_ROOT}/TSPi/scripts/install_wizard.py"
  --tspi-repo "${REPO_URL}" --tspi-ref "${REPO_REF}" "$@")
if [[ -t 0 || " $* " == *" --non-interactive "* ]]; then
  "${wizard[@]}"
elif { true </dev/tty; } 2>/dev/null; then
  "${wizard[@]}" </dev/tty
else
  "${wizard[@]}"
fi
