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
  readonly BOOTSTRAP_ACCENT=$'\033[1;36m' BOOTSTRAP_SUCCESS=$'\033[1;32m'
  readonly BOOTSTRAP_DANGER=$'\033[1;31m' BOOTSTRAP_RESET=$'\033[0m'
else
  readonly BOOTSTRAP_ACCENT="" BOOTSTRAP_SUCCESS="" BOOTSTRAP_DANGER="" BOOTSTRAP_RESET=""
fi

fail() {
  printf '%bTSPi installer failed:%b %s\n' "${BOOTSTRAP_DANGER}" "${BOOTSTRAP_RESET}" "$1" >&2
  exit "${2:-1}"
}

command -v python3 >/dev/null 2>&1 || fail "Python 3.11 or newer is required." 127
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is required."
if [[ -f "${SCRIPT_DIR}/scripts/install_wizard.py" && -f "${SCRIPT_DIR}/package.json" ]]; then
  exec python3 "${SCRIPT_DIR}/scripts/install_wizard.py" "$@"
fi
command -v git >/dev/null 2>&1 || fail "Git is required." 127

printf '\n%bTSPi Installer%b\n' "${BOOTSTRAP_ACCENT}" "${BOOTSTRAP_RESET}" >&2
printf '==============\n' >&2
printf 'Configure a reproducible TSPi installation.\n\n' >&2
printf 'Preparing source %s (%s)...\n' "${REPO_URL}" "${REPO_REF}" >&2

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tspi-installer.XXXXXX")"
readonly BOOTSTRAP_LOG="${TEMP_ROOT}/bootstrap.log"
BOOTSTRAP_SPINNER_PID=""
BOOTSTRAP_ANIMATIONS=true
for argument in "$@"; do
  [[ "${argument}" == "--json" ]] && BOOTSTRAP_ANIMATIONS=false
done

stop_bootstrap_spinner() {
  if [[ -n "${BOOTSTRAP_SPINNER_PID}" ]]; then
    kill "${BOOTSTRAP_SPINNER_PID}" 2>/dev/null || true
    wait "${BOOTSTRAP_SPINNER_PID}" 2>/dev/null || true
    BOOTSTRAP_SPINNER_PID=""
    printf '\r\033[2K' >&2
  fi
}

bootstrap_spinner() {
  local label="$1" frame index=0
  local -a frames=('|' '/' '-' $'\\')
  while true; do
    frame="${frames[index % ${#frames[@]}]}"
    printf '\r\033[2K  %b%s%b %s' "${BOOTSTRAP_ACCENT}" "${frame}" "${BOOTSTRAP_RESET}" "${label}" >&2
    index=$((index + 1))
    sleep 0.12
  done
}

cleanup() {
  stop_bootstrap_spinner
  rm -rf -- "${TEMP_ROOT}"
}
interrupted() { exit "$1"; }
trap cleanup EXIT
trap 'interrupted 130' INT
trap 'interrupted 143' TERM

run_bootstrap_step() {
  local label="$1"
  local status=0
  shift
  : >"${BOOTSTRAP_LOG}"
  if [[ "${BOOTSTRAP_ANIMATIONS}" == true && -t 2 && "${TERM:-}" != "dumb" ]]; then
    bootstrap_spinner "${label}" &
    BOOTSTRAP_SPINNER_PID=$!
  fi
  "$@" >"${BOOTSTRAP_LOG}" 2>&1 || status=$?
  stop_bootstrap_spinner
  if (( status != 0 )); then
    printf '%bFailed:%b %s\n' "${BOOTSTRAP_DANGER}" "${BOOTSTRAP_RESET}" "${label}" >&2
    sed -n '1,120p' "${BOOTSTRAP_LOG}" >&2
    exit "${status}"
  fi
  printf '  %bOK%b %s\n' "${BOOTSTRAP_SUCCESS}" "${BOOTSTRAP_RESET}" "${label}" >&2
}

run_bootstrap_step "repository access" git clone --quiet --filter=blob:none --no-checkout "${REPO_URL}" "${TEMP_ROOT}/TSPi"
run_bootstrap_step "revision ${REPO_REF}" git -C "${TEMP_ROOT}/TSPi" fetch --quiet --depth 1 origin "${REPO_REF}"
run_bootstrap_step "source checkout" git -C "${TEMP_ROOT}/TSPi" checkout --quiet --detach FETCH_HEAD
wizard=(python3 "${TEMP_ROOT}/TSPi/scripts/install_wizard.py"
  --tspi-repo "${REPO_URL}" --tspi-ref "${REPO_REF}" "$@")
non_interactive=false
for argument in "$@"; do
  [[ "${argument}" == "--non-interactive" ]] && non_interactive=true
done
if [[ -t 0 || "${non_interactive}" == true ]]; then
  TSPI_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}"
elif { true </dev/tty; } 2>/dev/null; then
  TSPI_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}" </dev/tty
else
  TSPI_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}"
fi
