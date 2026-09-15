#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_URL="${TSPI_INSTALL_REPO:-git@github.com:iawnix/TSPi.git}"
readonly REPO_REF="${TSPI_INSTALL_REF:-main}"
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
fi
readonly SCRIPT_DIR

if [[ -t 2 && ! -v NO_COLOR && "${TERM:-}" != "dumb" ]]; then
  readonly BOOTSTRAP_ACCENT=$'\033[1;33m' BOOTSTRAP_SUCCESS=$'\033[1;32m'
  readonly BOOTSTRAP_DANGER=$'\033[1;31m' BOOTSTRAP_RESET=$'\033[0m'
else
  readonly BOOTSTRAP_ACCENT="" BOOTSTRAP_SUCCESS="" BOOTSTRAP_DANGER="" BOOTSTRAP_RESET=""
fi

fail() {
  printf '%bTSPi uninstaller failed:%b %s\n' "${BOOTSTRAP_DANGER}" "${BOOTSTRAP_RESET}" "$1" >&2
  exit "${2:-1}"
}

command -v python3 >/dev/null 2>&1 || fail "Python 3.11 or newer is required." 127
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is required."
if [[ -f "${SCRIPT_DIR}/scripts/uninstall.py" && -f "${SCRIPT_DIR}/package.json" ]]; then
  exec python3 "${SCRIPT_DIR}/scripts/uninstall.py" "$@"
fi
if [[ -f "${SCRIPT_DIR}/.pi/tspi/uninstall.py" ]]; then
  exec python3 "${SCRIPT_DIR}/.pi/tspi/uninstall.py" "$@"
fi
command -v git >/dev/null 2>&1 || fail "Git is required for recovery mode." 127

printf '\n%bTSPi Uninstaller%b\n' "${BOOTSTRAP_ACCENT}" "${BOOTSTRAP_RESET}" >&2
printf 'Preparing source %s (%s)...\n' "${REPO_URL}" "${REPO_REF}" >&2

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tspi-uninstaller.XXXXXX")"
readonly BOOTSTRAP_LOG="${TEMP_ROOT}/bootstrap.log"
cleanup() { rm -rf -- "${TEMP_ROOT}"; }
interrupted() { exit "$1"; }
trap cleanup EXIT
trap 'interrupted 130' INT
trap 'interrupted 143' TERM

run_bootstrap_step() {
  local label="$1"
  shift
  : >"${BOOTSTRAP_LOG}"
  if ! "$@" >"${BOOTSTRAP_LOG}" 2>&1; then
    printf '%bFailed:%b %s\n' "${BOOTSTRAP_DANGER}" "${BOOTSTRAP_RESET}" "${label}" >&2
    sed -n '1,120p' "${BOOTSTRAP_LOG}" >&2
    exit 1
  fi
  printf '%bReady:%b %s\n' "${BOOTSTRAP_SUCCESS}" "${BOOTSTRAP_RESET}" "${label}" >&2
}

run_bootstrap_step "repository access" git clone --quiet --filter=blob:none --no-checkout "${REPO_URL}" "${TEMP_ROOT}/TSPi"
run_bootstrap_step "revision ${REPO_REF}" git -C "${TEMP_ROOT}/TSPi" fetch --quiet --depth 1 origin "${REPO_REF}"
run_bootstrap_step "source checkout" git -C "${TEMP_ROOT}/TSPi" checkout --quiet --detach FETCH_HEAD

uninstaller=(python3 "${TEMP_ROOT}/TSPi/scripts/uninstall.py" "$@")
if [[ -t 0 ]]; then
  "${uninstaller[@]}"
elif { true </dev/tty; } 2>/dev/null; then
  "${uninstaller[@]}" </dev/tty
else
  "${uninstaller[@]}"
fi
