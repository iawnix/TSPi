#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="${TSPI_INSTALL_REPO:-https://github.com/iawnix/TSPi.git}"
readonly REPO_REF="${TSPI_INSTALL_REF:-main}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ -f "${SCRIPT_DIR}/scripts/uninstall.py" && -f "${SCRIPT_DIR}/package.json" ]]; then
  exec python3 "${SCRIPT_DIR}/scripts/uninstall.py" "$@"
fi
if [[ -f "${SCRIPT_DIR}/.pi/tspi/uninstall.py" ]]; then
  exec python3 "${SCRIPT_DIR}/.pi/tspi/uninstall.py" "$@"
fi

command -v git >/dev/null 2>&1 || { echo "TSPi uninstaller requires Git." >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "TSPi uninstaller requires Python 3." >&2; exit 127; }

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tspi-uninstaller.XXXXXX")"
cleanup() { rm -rf -- "${TEMP_ROOT}"; }
trap cleanup EXIT INT TERM

git clone --filter=blob:none --no-checkout "${REPO_URL}" "${TEMP_ROOT}/TSPi"
git -C "${TEMP_ROOT}/TSPi" fetch --depth 1 origin "${REPO_REF}"
git -C "${TEMP_ROOT}/TSPi" checkout --detach FETCH_HEAD

uninstaller=(python3 "${TEMP_ROOT}/TSPi/scripts/uninstall.py" "$@")
if [[ -t 0 ]]; then
  "${uninstaller[@]}"
elif [[ -r /dev/tty ]]; then
  "${uninstaller[@]}" </dev/tty
else
  "${uninstaller[@]}"
fi
