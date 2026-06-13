#!/usr/bin/env bash
set -euo pipefail

# Template: source Gaussian safely under strict shell mode.
# Node-scoped usage:
#   RUN_DIR=nodes/<node_id>/outputs
#   INPUT=../inputs/<job>.gjf
# This keeps bare %chk=<job>.chk and Gaussian output files under outputs/.

RUN_DIR="${RUN_DIR:-$PWD}"
INPUT="${INPUT:?set INPUT to a Gaussian .gjf/.com path}"
INPUT_BASENAME="$(basename "$INPUT")"
OUTPUT="${OUTPUT:-${INPUT_BASENAME%.*}.out}"
G16ROOT="${G16ROOT:-/home/iaw/soft/Gaussian}"
G16="${G16:-/home/iaw/soft/Gaussian/g16/g16}"

cd "$RUN_DIR"
SCRATCH="${SCRATCH:-$(pwd -P)/../scratch/gaussian}"

export g16root="$G16ROOT"
if [[ -f "$g16root/g16/bsd/g16.profile" ]]; then
  set +e +u
  # shellcheck disable=SC1091
  source "$g16root/g16/bsd/g16.profile"
  profile_status=$?
  set -e -u
  if [[ $profile_status -ne 0 ]]; then
    echo "warning: g16.profile exited with status $profile_status" >&2
  fi
fi

export GAUSS_EXEDIR="$g16root/g16/bsd:$g16root/g16"
export G16BASIS="$g16root/g16/basis"
export PATH="$g16root/g16/bsd:$g16root/g16:$PATH"
export GAUSS_SCRDIR="$SCRATCH"
mkdir -p "$GAUSS_SCRDIR" "$(dirname "$OUTPUT")"

"$G16" < "$INPUT" > "$OUTPUT" 2> g16_driver.out

if [[ ! -s "$OUTPUT" ]]; then
  echo "error: expected Gaussian output missing or empty under outputs/: $RUN_DIR/$OUTPUT" >&2
  exit 91
fi
