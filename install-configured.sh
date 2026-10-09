#!/usr/bin/env bash
set -Eeuo pipefail

# ResearchAgent non-interactive installer wrapper.
#
# Edit the values in this file, or provide the corresponding RESEARCH_AGENT_* environment
# variable, then run:
#
#   ./install-configured.sh
#
# The wrapper calls the repository's install.sh so repository checkout,
# release validation, runtime setup, and service registration remain in one
# implementation.  Keep RESEARCH_AGENT_INSTALL_REF pinned to a commit for reproducible
# installations.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

INSTALL_ROOT="${RESEARCH_AGENT_INSTALL_ROOT:-$HOME/research-agent}"
WORKSPACE_ROOT="${RESEARCH_AGENT_WORKSPACE_ROOT:-$INSTALL_ROOT/workspaces}"
RESEARCH_AGENT_REPO="${RESEARCH_AGENT_INSTALL_REPO:-https://github.com/iawnix/TSPi.git}"
RESEARCH_AGENT_REF="${RESEARCH_AGENT_INSTALL_REF:-main}"
CONDA_ROOT="${RESEARCH_AGENT_CONDA_ROOT:-}"

# Use installation-owned copies of these files by default. Replace either
# path with an administrator-maintained file when needed.
COMPUTE_CONFIG="${RESEARCH_AGENT_COMPUTE_CONFIG:-$SCRIPT_DIR/config/compute.example.toml}"
NAME_RESOLVER_CONFIG="${RESEARCH_AGENT_NAME_RESOLVER_CONFIG:-$SCRIPT_DIR/config/name-resolver.example.toml}"

SERVICE_SCOPE="${RESEARCH_AGENT_SERVICE_SCOPE:-user}"
SERVICE_USER="${RESEARCH_AGENT_SERVICE_USER:-}"
ENABLE_SERVICES="${RESEARCH_AGENT_ENABLE_SERVICES:-true}"
START_SERVICES="${RESEARCH_AGENT_START_SERVICES:-true}"

WITH_LINK_RELAY="${RESEARCH_AGENT_WITH_LINK_RELAY:-true}"
RELAY_INSTALL_ROOT="${RESEARCH_AGENT_LINK_RELAY_ROOT:-$INSTALL_ROOT/.pi/link-relay}"
RELAY_STATE_DIR="${RESEARCH_AGENT_LINK_RELAY_STATE_DIR:-$INSTALL_ROOT/.pi/link-relay-state}"
RELAY_PUBLIC_URL="${RESEARCH_AGENT_LINK_URL:-https://tsphone.iawnix.xyz}"
RELAY_LISTEN="${RESEARCH_AGENT_LINK_RELAY_LISTEN:-127.0.0.1}"
RELAY_PORT="${RESEARCH_AGENT_LINK_RELAY_PORT:-8788}"
RELAY_SERVICE_SCOPE="${RESEARCH_AGENT_LINK_RELAY_SERVICE_SCOPE:-user}"
RELAY_SERVICE_USER="${RESEARCH_AGENT_LINK_RELAY_SERVICE_USER:-research-agent-relay}"
RELAY_ENABLE_SERVICES="${RESEARCH_AGENT_LINK_RELAY_ENABLE_SERVICES:-true}"
RELAY_START_SERVICES="${RESEARCH_AGENT_LINK_RELAY_START_SERVICES:-true}"

WITH_WEB="${RESEARCH_AGENT_WITH_WEB:-false}"
WEB_PORT="${RESEARCH_AGENT_WEB_PORT:-}"
WEB_HOST="${RESEARCH_AGENT_WEB_HOST:-127.0.0.1}"
ALLOW_REMOTE="${RESEARCH_AGENT_ALLOW_REMOTE:-false}"
WEB_AUTH_TOKEN_FILE="${RESEARCH_AGENT_WEB_AUTH_TOKEN_FILE:-}"
WEB_AUTH_TOKEN="${RESEARCH_AGENT_WEB_AUTH_TOKEN:-}"

WITH_MODEL_ICONS="${RESEARCH_AGENT_WITH_MODEL_ICONS:-false}"
PHONE_ACCESS="${RESEARCH_AGENT_PHONE_ACCESS:-link}"
LINK_RELAY_ROOT="${RESEARCH_AGENT_LINK_RELAY_ROOT:-}"
LINK_URL="${RESEARCH_AGENT_LINK_URL:-}"
LINK_ENROLLMENT_URL="${RESEARCH_AGENT_LINK_ENROLLMENT_URL:-}"
LINK_ENROLLMENT_CODE="${RESEARCH_AGENT_LINK_ENROLLMENT_CODE:-}"
PROBE_REMOTE="${RESEARCH_AGENT_PROBE_REMOTE:-false}"

EMAIL_BINDING="${RESEARCH_AGENT_EMAIL_BINDING:-}"
EMAIL_PRESET="${RESEARCH_AGENT_EMAIL_PRESET:-}"
EMAIL_HOST="${RESEARCH_AGENT_EMAIL_HOST:-}"
EMAIL_RECIPIENT="${RESEARCH_AGENT_EMAIL_RECIPIENT:-}"
EMAIL_USERNAME="${RESEARCH_AGENT_EMAIL_USERNAME:-}"
EMAIL_PORT="${RESEARCH_AGENT_EMAIL_PORT:-}"
EMAIL_SECURITY="${RESEARCH_AGENT_EMAIL_SECURITY:-}"
CLAWEMAIL_ROOT="${RESEARCH_AGENT_CLAWEMAIL_ROOT:-}"
EMAIL_PASSWORD_ENV="${RESEARCH_AGENT_EMAIL_PASSWORD_ENV:-}"
EMAIL_PASSWORD_FILE="${RESEARCH_AGENT_EMAIL_PASSWORD_FILE:-}"

truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    0|false|no|off|"") return 1 ;;
    *) printf 'invalid boolean value: %s\n' "$1" >&2; return 2 ;;
  esac
}

validate_boolean() {
  case "${1,,}" in
    1|true|yes|on|0|false|no|off|"") ;;
    *) printf 'invalid boolean value: %s\n' "$1" >&2; exit 2 ;;
  esac
}

append_value() {
  local flag="$1" value="$2"
  if [[ -n "$value" ]]; then
    INSTALL_ARGS+=("$flag" "$value")
  fi
}

usage() {
  cat <<'EOF'
Usage: install-configured.sh [--dry-run] [additional install.sh options]

Configuration is read from the variables near the top of this file. Every
variable also accepts a RESEARCH_AGENT_* environment override. The wrapper always uses
--non-interactive --yes; additional arguments are appended to install.sh.

Important variables:
  RESEARCH_AGENT_INSTALL_ROOT, RESEARCH_AGENT_WORKSPACE_ROOT, RESEARCH_AGENT_INSTALL_REPO, RESEARCH_AGENT_INSTALL_REF
  RESEARCH_AGENT_COMPUTE_CONFIG, RESEARCH_AGENT_NAME_RESOLVER_CONFIG, RESEARCH_AGENT_CONDA_ROOT
  RESEARCH_AGENT_SERVICE_SCOPE, RESEARCH_AGENT_SERVICE_USER, RESEARCH_AGENT_ENABLE_SERVICES, RESEARCH_AGENT_START_SERVICES
  RESEARCH_AGENT_WITH_LINK_RELAY, RESEARCH_AGENT_LINK_RELAY_ROOT, RESEARCH_AGENT_LINK_RELAY_STATE_DIR
  RESEARCH_AGENT_LINK_URL, RESEARCH_AGENT_LINK_RELAY_LISTEN, RESEARCH_AGENT_LINK_RELAY_PORT
  RESEARCH_AGENT_LINK_RELAY_SERVICE_SCOPE, RESEARCH_AGENT_LINK_RELAY_SERVICE_USER
  RESEARCH_AGENT_LINK_RELAY_ENABLE_SERVICES, RESEARCH_AGENT_LINK_RELAY_START_SERVICES
  RESEARCH_AGENT_WITH_WEB, RESEARCH_AGENT_WEB_PORT, RESEARCH_AGENT_WEB_HOST, RESEARCH_AGENT_ALLOW_REMOTE
  RESEARCH_AGENT_WEB_AUTH_TOKEN_FILE, RESEARCH_AGENT_WEB_AUTH_TOKEN
  RESEARCH_AGENT_PHONE_ACCESS, RESEARCH_AGENT_LINK_RELAY_ROOT, RESEARCH_AGENT_LINK_URL
  RESEARCH_AGENT_LINK_ENROLLMENT_URL
  RESEARCH_AGENT_LINK_ENROLLMENT_CODE, RESEARCH_AGENT_PROBE_REMOTE
  RESEARCH_AGENT_EMAIL_BINDING, RESEARCH_AGENT_EMAIL_PRESET, RESEARCH_AGENT_EMAIL_HOST, RESEARCH_AGENT_EMAIL_RECIPIENT
  RESEARCH_AGENT_EMAIL_USERNAME, RESEARCH_AGENT_EMAIL_PORT, RESEARCH_AGENT_EMAIL_SECURITY
  RESEARCH_AGENT_CLAWEMAIL_ROOT, RESEARCH_AGENT_EMAIL_PASSWORD_ENV, RESEARCH_AGENT_EMAIL_PASSWORD_FILE

Pin RESEARCH_AGENT_INSTALL_REF to a full commit SHA for a reproducible installation.
EOF
}

DRY_RUN=false
EXTRA_ARGS=()
while (($#)); do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --) shift; EXTRA_ARGS+=("$@"); break ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

[[ -x "$SCRIPT_DIR/install.sh" ]] || {
  printf 'missing executable installer: %s\n' "$SCRIPT_DIR/install.sh" >&2
  exit 1
}
[[ "$SERVICE_SCOPE" == none || "$SERVICE_SCOPE" == user || "$SERVICE_SCOPE" == system ]] || {
  printf 'RESEARCH_AGENT_SERVICE_SCOPE must be none, user, or system\n' >&2
  exit 2
}
[[ "$PHONE_ACCESS" == disabled || "$PHONE_ACCESS" == link ]] || {
  printf 'RESEARCH_AGENT_PHONE_ACCESS must be disabled or link\n' >&2
  exit 2
}
validate_boolean "$WITH_WEB"
validate_boolean "$WITH_MODEL_ICONS"
validate_boolean "$ALLOW_REMOTE"
validate_boolean "$PROBE_REMOTE"
validate_boolean "$ENABLE_SERVICES"
validate_boolean "$START_SERVICES"
validate_boolean "$WITH_LINK_RELAY"
validate_boolean "$RELAY_ENABLE_SERVICES"
validate_boolean "$RELAY_START_SERVICES"

INSTALL_ARGS=(
  --install-root "$INSTALL_ROOT"
  --workspace-root "$WORKSPACE_ROOT"
  --research-agent-repo "$RESEARCH_AGENT_REPO"
  --research-agent-ref "$RESEARCH_AGENT_REF"
  --service-scope "$SERVICE_SCOPE"
  --phone-access "$PHONE_ACCESS"
  --compute-config "$COMPUTE_CONFIG"
  --name-resolver-config "$NAME_RESOLVER_CONFIG"
  --non-interactive
  --yes
)
append_value --conda-root "$CONDA_ROOT"
append_value --service-user "$SERVICE_USER"
append_value --web-port "$WEB_PORT"
append_value --web-host "$WEB_HOST"
append_value --web-auth-token-file "$WEB_AUTH_TOKEN_FILE"
append_value --web-auth-token "$WEB_AUTH_TOKEN"
append_value --link-relay-root "$LINK_RELAY_ROOT"
append_value --link-url "$LINK_URL"
append_value --link-enrollment-url "$LINK_ENROLLMENT_URL"
append_value --link-enrollment-code "$LINK_ENROLLMENT_CODE"
append_value --email-binding "$EMAIL_BINDING"
append_value --email-preset "$EMAIL_PRESET"
append_value --email-host "$EMAIL_HOST"
append_value --email-recipient "$EMAIL_RECIPIENT"
append_value --email-address "$EMAIL_USERNAME"
append_value --email-port "$EMAIL_PORT"
append_value --email-security "$EMAIL_SECURITY"
append_value --clawemail-root "$CLAWEMAIL_ROOT"
append_value --email-password-env "$EMAIL_PASSWORD_ENV"
append_value --email-password-file "$EMAIL_PASSWORD_FILE"

if truthy "$WITH_LINK_RELAY"; then
  [[ "$PHONE_ACCESS" == link ]] || {
    printf 'RESEARCH_AGENT_PHONE_ACCESS must be link when RESEARCH_AGENT_WITH_LINK_RELAY is enabled\n' >&2
    exit 2
  }
  [[ -n "$RELAY_PUBLIC_URL" ]] || {
    printf 'RESEARCH_AGENT_LINK_URL is required when RESEARCH_AGENT_WITH_LINK_RELAY is enabled\n' >&2
    exit 2
  }
  INSTALL_ARGS+=(
    --with-link-relay
    --relay-install-root "$RELAY_INSTALL_ROOT"
    --relay-state-dir "$RELAY_STATE_DIR"
    --relay-public-url "$RELAY_PUBLIC_URL"
    --relay-listen "$RELAY_LISTEN"
    --relay-port "$RELAY_PORT"
    --relay-service-scope "$RELAY_SERVICE_SCOPE"
    --relay-service-user "$RELAY_SERVICE_USER"
  )
  if [[ "$RELAY_SERVICE_SCOPE" == none ]]; then
    # The Relay installer rejects service actions with scope=none. Treat this
    # scope as an explicit request to install the release and state only.
    INSTALL_ARGS+=(--relay-no-enable-services --relay-no-start-services)
  else
    if truthy "$RELAY_ENABLE_SERVICES"; then INSTALL_ARGS+=(--relay-enable-services); else INSTALL_ARGS+=(--relay-no-enable-services); fi
    if truthy "$RELAY_START_SERVICES"; then INSTALL_ARGS+=(--relay-start-services); else INSTALL_ARGS+=(--relay-no-start-services); fi
  fi
fi

if truthy "$WITH_WEB"; then INSTALL_ARGS+=(--with-web); else INSTALL_ARGS+=(--without-web); fi
if truthy "$WITH_MODEL_ICONS"; then INSTALL_ARGS+=(--with-model-icons); else INSTALL_ARGS+=(--without-model-icons); fi
if truthy "$ALLOW_REMOTE"; then INSTALL_ARGS+=(--allow-remote); fi
if truthy "$PROBE_REMOTE"; then INSTALL_ARGS+=(--probe-remote); fi
if [[ "$SERVICE_SCOPE" != none ]] && truthy "$ENABLE_SERVICES"; then INSTALL_ARGS+=(--enable-services); fi
if [[ "$SERVICE_SCOPE" != none ]] && truthy "$START_SERVICES"; then INSTALL_ARGS+=(--start-services); fi

INSTALL_ARGS+=("${EXTRA_ARGS[@]}")

print_dry_run_args() {
  local redact_next=false argument
  for argument in "$@"; do
    if [[ "$redact_next" == true ]]; then
      printf '%q ' '[REDACTED]'
      redact_next=false
      continue
    fi
    case "$argument" in
      --web-auth-token|--link-enrollment-code)
        printf '%q ' "$argument"
        redact_next=true
        ;;
      --web-auth-token=*|--link-enrollment-code=*)
        printf '%q ' "${argument%%=*}=[REDACTED]"
        ;;
      *)
        printf '%q ' "$argument"
        ;;
    esac
  done
}

if [[ "$DRY_RUN" == true ]]; then
  printf 'Would run:\n  '
  print_dry_run_args "$SCRIPT_DIR/install.sh" "${INSTALL_ARGS[@]}"
  printf '\n'
  exit 0
fi

exec "$SCRIPT_DIR/install.sh" "${INSTALL_ARGS[@]}"
