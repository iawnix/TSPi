#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${RESEARCH_AGENT_INSTALL_REPO:-https://github.com/iawnix/TSPi.git}"
REPO_REF="${RESEARCH_AGENT_INSTALL_REF:-main}"
WITH_LINK_RELAY="${RESEARCH_AGENT_WITH_LINK_RELAY:-false}"
RELAY_INSTALL_ROOT="${RESEARCH_AGENT_LINK_RELAY_ROOT:-}"
RELAY_STATE_DIR="${RESEARCH_AGENT_LINK_RELAY_STATE_DIR:-}"
RELAY_PUBLIC_URL="${RESEARCH_AGENT_LINK_URL:-}"
RELAY_LISTEN="${RESEARCH_AGENT_LINK_RELAY_LISTEN:-127.0.0.1}"
RELAY_PORT="${RESEARCH_AGENT_LINK_RELAY_PORT:-8788}"
RELAY_SERVICE_SCOPE="${RESEARCH_AGENT_LINK_RELAY_SERVICE_SCOPE:-user}"
RELAY_SERVICE_USER="${RESEARCH_AGENT_LINK_RELAY_SERVICE_USER:-research-agent-relay}"
RELAY_ENABLE_SERVICES="${RESEARCH_AGENT_LINK_RELAY_ENABLE_SERVICES:-true}"
RELAY_START_SERVICES="${RESEARCH_AGENT_LINK_RELAY_START_SERVICES:-true}"
FORWARD_ARGS=()

if [[ -t 2 && ! -v NO_COLOR && "${TERM:-}" != "dumb" ]]; then
  readonly BOOTSTRAP_ACCENT=$'\033[1;36m' BOOTSTRAP_SUCCESS=$'\033[1;32m'
  readonly BOOTSTRAP_DANGER=$'\033[1;31m' BOOTSTRAP_RESET=$'\033[0m'
else
  readonly BOOTSTRAP_ACCENT="" BOOTSTRAP_SUCCESS="" BOOTSTRAP_DANGER="" BOOTSTRAP_RESET=""
fi

fail() {
  printf '%bResearchAgent installer failed:%b %s\n' "${BOOTSTRAP_DANGER}" "${BOOTSTRAP_RESET}" "$1" >&2
  exit "${2:-1}"
}

truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    0|false|no|off) return 1 ;;
    *) fail "invalid boolean value: $1" 2 ;;
  esac
}

usage() {
  cat <<'EOF'
Usage: install.sh [installer options]

This bootstrap resolves the selected Git revision, then invokes the Python
installer from that immutable checkout. All options not handled here are
forwarded to scripts/install_wizard.py.

Bootstrap options:
  --research-agent-repo URL, --research-agent-ref REF
  --with-link-relay / --without-link-relay
  --relay-install-root PATH, --relay-state-dir PATH
  --relay-public-url URL, --relay-listen HOST, --relay-port PORT
  --relay-service-scope {user,system,none}
  --relay-service-user ACCOUNT
  --relay-enable-services / --relay-no-enable-services
  --relay-start-services / --relay-no-start-services

Relay integration is non-interactive. It installs the Relay first, obtains a
one-time enrollment code, and forwards the code to the Host installer.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

command -v python3 >/dev/null 2>&1 || fail "Python 3.11 or newer is required." 127
python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || fail "Python 3.11 or newer is required."
command -v git >/dev/null 2>&1 || fail "Git is required." 127

while (( $# )); do
  case "$1" in
    --research-agent-repo)
      (( $# >= 2 )) || fail "--research-agent-repo requires a value."
      REPO_URL="$2"
      shift 2
      ;;
    --research-agent-repo=*)
      REPO_URL="${1#*=}"
      shift
      ;;
    --research-agent-ref)
      (( $# >= 2 )) || fail "--research-agent-ref requires a value."
      REPO_REF="$2"
      shift 2
      ;;
    --research-agent-ref=*)
      REPO_REF="${1#*=}"
      shift
      ;;
    --research-agent-commit|--research-agent-commit=*)
      fail "--research-agent-commit is reserved for the installer bootstrap."
      ;;
    --source-root|--source-root=*)
      fail "--source-root is reserved for the installer bootstrap."
      ;;
    --with-link-relay)
      WITH_LINK_RELAY=true
      shift
      ;;
    --without-link-relay)
      WITH_LINK_RELAY=false
      shift
      ;;
    --relay-install-root)
      (( $# >= 2 )) || fail "--relay-install-root requires a value."
      RELAY_INSTALL_ROOT="$2"
      shift 2
      ;;
    --relay-install-root=*)
      RELAY_INSTALL_ROOT="${1#*=}"
      shift
      ;;
    --relay-state-dir)
      (( $# >= 2 )) || fail "--relay-state-dir requires a value."
      RELAY_STATE_DIR="$2"
      shift 2
      ;;
    --relay-state-dir=*)
      RELAY_STATE_DIR="${1#*=}"
      shift
      ;;
    --relay-public-url)
      (( $# >= 2 )) || fail "--relay-public-url requires a value."
      RELAY_PUBLIC_URL="$2"
      shift 2
      ;;
    --relay-public-url=*)
      RELAY_PUBLIC_URL="${1#*=}"
      shift
      ;;
    --relay-listen)
      (( $# >= 2 )) || fail "--relay-listen requires a value."
      RELAY_LISTEN="$2"
      shift 2
      ;;
    --relay-listen=*)
      RELAY_LISTEN="${1#*=}"
      shift
      ;;
    --relay-port)
      (( $# >= 2 )) || fail "--relay-port requires a value."
      RELAY_PORT="$2"
      shift 2
      ;;
    --relay-port=*)
      RELAY_PORT="${1#*=}"
      shift
      ;;
    --relay-service-scope)
      (( $# >= 2 )) || fail "--relay-service-scope requires a value."
      RELAY_SERVICE_SCOPE="$2"
      shift 2
      ;;
    --relay-service-scope=*)
      RELAY_SERVICE_SCOPE="${1#*=}"
      shift
      ;;
    --relay-service-user)
      (( $# >= 2 )) || fail "--relay-service-user requires a value."
      RELAY_SERVICE_USER="$2"
      shift 2
      ;;
    --relay-service-user=*)
      RELAY_SERVICE_USER="${1#*=}"
      shift
      ;;
    --relay-enable-services)
      RELAY_ENABLE_SERVICES=true
      shift
      ;;
    --relay-no-enable-services)
      RELAY_ENABLE_SERVICES=false
      shift
      ;;
    --relay-start-services)
      RELAY_START_SERVICES=true
      shift
      ;;
    --relay-no-start-services)
      RELAY_START_SERVICES=false
      shift
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done
[[ -n "${REPO_URL}" ]] || fail "--research-agent-repo must not be empty."
if [[ ! "${REPO_REF}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$ || "${REPO_REF}" == *..* ]]; then
  fail "--research-agent-ref must be a branch, tag, or full 40-character commit SHA."
fi
truthy "${WITH_LINK_RELAY}" >/dev/null || true
truthy "${RELAY_ENABLE_SERVICES}" >/dev/null || true
truthy "${RELAY_START_SERVICES}" >/dev/null || true
[[ "${RELAY_SERVICE_SCOPE}" == system || "${RELAY_SERVICE_SCOPE}" == user || "${RELAY_SERVICE_SCOPE}" == none ]] \
  || fail "--relay-service-scope must be system, user, or none."
if truthy "${WITH_LINK_RELAY}"; then
  [[ -n "${RELAY_PUBLIC_URL}" ]] || fail "--relay-public-url is required with --with-link-relay."
  if [[ "${RELAY_SERVICE_SCOPE}" == system ]]; then
    [[ -n "${RELAY_INSTALL_ROOT}" ]] || RELAY_INSTALL_ROOT=/opt/research-agent-relay
    [[ -n "${RELAY_STATE_DIR}" ]] || RELAY_STATE_DIR=/var/lib/research-agent-relay
  else
    [[ -n "${RELAY_INSTALL_ROOT}" ]] || RELAY_INSTALL_ROOT="${HOME}/.local/share/research-agent-relay"
    [[ -n "${RELAY_STATE_DIR}" ]] || RELAY_STATE_DIR="${HOME}/.local/state/research-agent-relay"
  fi
  non_interactive=false
  for argument in "${FORWARD_ARGS[@]}"; do
    [[ "${argument}" == "--non-interactive" ]] && non_interactive=true
  done
  [[ "${non_interactive}" == true ]] || fail "--with-link-relay requires --non-interactive so Relay side effects occur only after explicit configuration."
fi
readonly REPO_URL REPO_REF

printf '\n%bResearchAgent Installer%b\n' "${BOOTSTRAP_ACCENT}" "${BOOTSTRAP_RESET}" >&2
printf '==============\n' >&2
printf 'Configure a reproducible ResearchAgent installation.\n\n' >&2
printf 'Preparing source %s (%s)...\n' "${REPO_URL}" "${REPO_REF}" >&2

readonly TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/research-agent-installer.XXXXXX")"
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

extract_relay_enrollment_code() {
  local output_path="$1"
  python3 - "${output_path}" <<'PY'
import json
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
decoder = json.JSONDecoder()
objects = []
for index, character in enumerate(text):
    if character != "{":
        continue
    try:
        value, _ = decoder.raw_decode(text[index:])
    except json.JSONDecodeError:
        continue
    if isinstance(value, dict):
        objects.append(value)
for value in reversed(objects):
    enrollment = value.get("enrollment")
    code = enrollment.get("code") if isinstance(enrollment, dict) else None
    if isinstance(code, str) and code:
        print(code)
        raise SystemExit(0)
raise SystemExit("Link Relay installer did not return an enrollment code")
PY
}

install_embedded_relay() {
  local relay_log="${TEMP_ROOT}/link-relay-install.log"
  local -a relay_args=(
    python3 "${TEMP_ROOT}/ResearchAgent/scripts/install_link_relay.py"
    --install-root "${RELAY_INSTALL_ROOT}"
    --state-dir "${RELAY_STATE_DIR}"
    --public-url "${RELAY_PUBLIC_URL}"
    --listen "${RELAY_LISTEN}"
    --port "${RELAY_PORT}"
    --service-scope "${RELAY_SERVICE_SCOPE}"
    --service-user "${RELAY_SERVICE_USER}"
    --source-root "${TEMP_ROOT}/ResearchAgent"
    --non-interactive
    --yes
    --json
  )
  if [[ "${RELAY_SERVICE_SCOPE}" != none ]]; then
    if truthy "${RELAY_ENABLE_SERVICES}"; then relay_args+=(--enable-services); fi
    if truthy "${RELAY_START_SERVICES}"; then relay_args+=(--start-services); fi
  fi
  run_bootstrap_step "Link Relay installation" "${relay_args[@]}"
  cp -- "${BOOTSTRAP_LOG}" "${relay_log}"
  RELAY_ENROLLMENT_CODE="$(extract_relay_enrollment_code "${relay_log}")" \
    || fail "Link Relay installation did not produce an enrollment code; see ${relay_log}."
  FORWARD_ARGS+=(
    --phone-access link
    --link-relay-root "${RELAY_INSTALL_ROOT}"
    --link-url "${RELAY_PUBLIC_URL}"
    --link-enrollment-code "${RELAY_ENROLLMENT_CODE}"
  )
  case "${RELAY_LISTEN}" in
    127.0.0.1|localhost)
      FORWARD_ARGS+=(--link-enrollment-url "http://${RELAY_LISTEN}:${RELAY_PORT}")
      ;;
    ::1)
      FORWARD_ARGS+=(--link-enrollment-url "http://[${RELAY_LISTEN}]:${RELAY_PORT}")
      ;;
  esac
}

relay_marker_for_host() {
  local argument index
  for ((index = 0; index < ${#FORWARD_ARGS[@]}; index++)); do
    argument="${FORWARD_ARGS[index]}"
    if [[ "${argument}" == "--install-root" && $((index + 1)) -lt ${#FORWARD_ARGS[@]} ]]; then
      printf '%s' "${FORWARD_ARGS[index + 1]}"
      return 0
    fi
    if [[ "${argument}" == --install-root=* ]]; then
      printf '%s' "${argument#*=}"
      return 0
    fi
  done
  return 1
}

write_relay_ownership_marker() {
  local host_root
  host_root="$(relay_marker_for_host)" || fail "--install-root is required when embedding a Link Relay."
  python3 - "${host_root}" "${RELAY_INSTALL_ROOT}" "${RELAY_STATE_DIR}" "${RELAY_SERVICE_SCOPE}" <<'PY'
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).expanduser().resolve()
marker = root / ".pi" / "link-relay.json"
marker.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
marker.parent.chmod(0o700)
value = {
    "schema": "research-agent-install-link-relay/1",
    "install_root": str(root),
    "relay_install_root": str(Path(sys.argv[2]).expanduser().resolve()),
    "state_dir": str(Path(sys.argv[3]).expanduser().resolve()),
    "service_scope": sys.argv[4],
    "owned": True,
}
temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
with temporary.open("w", encoding="utf-8") as handle:
    os.chmod(temporary, 0o600)
    json.dump(value, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, marker)
os.chmod(marker, 0o600)
PY
}

run_bootstrap_step "repository access" git_clone_source "${TEMP_ROOT}/ResearchAgent"
run_bootstrap_step "revision ${REPO_REF}" git_fetch_revision "${TEMP_ROOT}/ResearchAgent"
run_bootstrap_step "source checkout" git -C "${TEMP_ROOT}/ResearchAgent" checkout --quiet --detach FETCH_HEAD
RESOLVED_COMMIT="$(git -C "${TEMP_ROOT}/ResearchAgent" rev-parse --verify 'HEAD^{commit}')" \
  || fail "could not read the resolved ResearchAgent commit."
[[ "${RESOLVED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] \
  || fail "resolved ResearchAgent revision is not a full commit SHA."
readonly RESOLVED_COMMIT
if truthy "${WITH_LINK_RELAY}"; then
  install_embedded_relay
fi
wizard=(python3 "${TEMP_ROOT}/ResearchAgent/scripts/install_wizard.py"
  --research-agent-repo "${REPO_URL}" --research-agent-ref "${REPO_REF}"
  --research-agent-commit "${RESOLVED_COMMIT}" --source-root "${TEMP_ROOT}/ResearchAgent"
  "${FORWARD_ARGS[@]}")
non_interactive=false
for argument in "${FORWARD_ARGS[@]}"; do
  [[ "${argument}" == "--non-interactive" ]] && non_interactive=true
done
if [[ -t 0 || "${non_interactive}" == true ]]; then
  RESEARCH_AGENT_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}"
elif { true </dev/tty; } 2>/dev/null; then
  RESEARCH_AGENT_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}" </dev/tty
else
  RESEARCH_AGENT_INSTALL_BOOTSTRAPPED=1 "${wizard[@]}"
fi
if truthy "${WITH_LINK_RELAY}"; then
  write_relay_ownership_marker
fi
