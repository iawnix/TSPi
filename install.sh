#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${TSPI_INSTALL_REPO:-https://github.com/iawnix/TSPi.git}"
REPO_REF="${TSPI_INSTALL_REF:-main}"
FORWARD_ARGS=()

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
command -v git >/dev/null 2>&1 || fail "Git is required." 127

while (( $# )); do
  case "$1" in
    --tspi-repo)
      (( $# >= 2 )) || fail "--tspi-repo requires a value."
      REPO_URL="$2"
      shift 2
      ;;
    --tspi-repo=*)
      REPO_URL="${1#*=}"
      shift
      ;;
    --tspi-ref)
      (( $# >= 2 )) || fail "--tspi-ref requires a value."
      REPO_REF="$2"
      shift 2
      ;;
    --tspi-ref=*)
      REPO_REF="${1#*=}"
      shift
      ;;
    --tspi-commit|--tspi-commit=*)
      fail "--tspi-commit is reserved for the installer bootstrap."
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done
[[ -n "${REPO_URL}" ]] || fail "--tspi-repo must not be empty."
if [[ ! "${REPO_REF}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$ || "${REPO_REF}" == *..* ]]; then
  fail "--tspi-ref must be a branch, tag, or full 40-character commit SHA."
fi
readonly REPO_URL REPO_REF

printf '\n%bTSPi Installer%b\n' "${BOOTSTRAP_ACCENT}" "${BOOTSTRAP_RESET}" >&2
printf '==============\n' >&2
printf 'Configure a reproducible TSPi installation.\n\n' >&2
printf 'Preparing source %s (%s)...\n' "${REPO_URL}" "${REPO_REF}" >&2

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/tspi-installer.XXXXXX")"
readonly BOOTSTRAP_LOG="${TEMP_ROOT}/bootstrap.log"
BOOTSTRAP_SPINNER_PID=""
BOOTSTRAP_ANIMATIONS=true
for argument in "${FORWARD_ARGS[@]}"; do
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

git_clone_source() {
  local destination="$1" attempt
  for ((attempt = 1; attempt <= 3; attempt++)); do
    if git clone --quiet --filter=blob:none --no-checkout -- "${REPO_URL}" "${destination}"; then
      return 0
    fi
    rm -rf -- "${destination}"
    if (( attempt < 3 )); then
      sleep "${attempt}"
    fi
  done
  return 1
}

git_fetch_revision() {
  local checkout="$1" attempt fallback
  for ((attempt = 1; attempt <= 3; attempt++)); do
    if git -C "${checkout}" fetch --quiet --depth 1 origin "${REPO_REF}"; then
      return 0
    fi
    if (( attempt < 3 )); then
      sleep "${attempt}"
    fi
  done

  # A proxy or Git server may terminate partial-clone pack transfers. Retry
  # with a regular shallow clone, which avoids the filter negotiation.
  fallback="${checkout}.fallback"
  for ((attempt = 1; attempt <= 3; attempt++)); do
    rm -rf -- "${fallback}"
    if git clone --quiet --depth 1 --no-checkout -- "${REPO_URL}" "${fallback}" \
      && git -C "${fallback}" fetch --quiet --depth 1 origin "${REPO_REF}"; then
      rm -rf -- "${checkout}"
      mv -- "${fallback}" "${checkout}"
      return 0
    fi
    if (( attempt < 3 )); then
      sleep "${attempt}"
    fi
  done
  rm -rf -- "${fallback}"
  return 1
}

run_bootstrap_step "repository access" git_clone_source "${TEMP_ROOT}/TSPi"
run_bootstrap_step "revision ${REPO_REF}" git_fetch_revision "${TEMP_ROOT}/TSPi"
run_bootstrap_step "source checkout" git -C "${TEMP_ROOT}/TSPi" checkout --quiet --detach FETCH_HEAD
RESOLVED_COMMIT="$(git -C "${TEMP_ROOT}/TSPi" rev-parse --verify 'HEAD^{commit}')" \
  || fail "could not read the resolved TSPi commit."
[[ "${RESOLVED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] \
  || fail "resolved TSPi revision is not a full commit SHA."
readonly RESOLVED_COMMIT
wizard=(python3 "${TEMP_ROOT}/TSPi/scripts/install_wizard.py"
  --tspi-repo "${REPO_URL}" --tspi-ref "${REPO_REF}"
  --tspi-commit "${RESOLVED_COMMIT}" "${FORWARD_ARGS[@]}")
non_interactive=false
for argument in "${FORWARD_ARGS[@]}"; do
  [[ "${argument}" == "--non-interactive" ]] && non_interactive=true
done
if [[ -t 0 || "${non_interactive}" == true ]]; then
  TSPI_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}"
elif { true </dev/tty; } 2>/dev/null; then
  TSPI_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}" </dev/tty
else
  TSPI_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}"
fi
