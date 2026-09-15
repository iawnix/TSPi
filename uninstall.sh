#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="${TSPI_INSTALL_REPO:-git@github.com:iawnix/TSPi.git}"
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

if [[ -t 2 && ! -v NO_COLOR && "${TERM:-}" != "dumb" ]]; then
  readonly BOOTSTRAP_ACCENT=$'\033[1;33m' BOOTSTRAP_RESET=$'\033[0m'
else
  readonly BOOTSTRAP_ACCENT="" BOOTSTRAP_RESET=""
fi
printf '\n%bTSPi Uninstaller%b\n' "${BOOTSTRAP_ACCENT}" "${BOOTSTRAP_RESET}" >&2
printf 'Preparing source %s (%s)...\n' "${REPO_URL}" "${REPO_REF}" >&2

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tspi-uninstaller.XXXXXX")"
cleanup() { rm -rf -- "${TEMP_ROOT}"; }
trap cleanup EXIT INT TERM

git clone --quiet --filter=blob:none --no-checkout "${REPO_URL}" "${TEMP_ROOT}/TSPi"
git -C "${TEMP_ROOT}/TSPi" fetch --quiet --depth 1 origin "${REPO_REF}"
git -C "${TEMP_ROOT}/TSPi" checkout --quiet --detach FETCH_HEAD

uninstaller=(python3 "${TEMP_ROOT}/TSPi/scripts/uninstall.py" "$@")
if [[ -t 0 ]]; then
  "${uninstaller[@]}"
elif [[ -r /dev/tty ]]; then
  "${uninstaller[@]}" </dev/tty
else
  "${uninstaller[@]}"
fi
