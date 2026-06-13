#!/usr/bin/env bash
set -euo pipefail

# Template: run independent plus/minus displacement endpoint optimizations
# concurrently. Expected input files:
#   inputs/minus_endpoint_opt.gjf
#   inputs/plus_endpoint_opt.gjf

NODE_DIR="${NODE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
G16ROOT="${G16ROOT:-/home/iaw/soft/Gaussian}"
G16="${G16:-/home/iaw/soft/Gaussian/g16/g16}"
SCRATCH_ROOT="${SCRATCH_ROOT:-${NODE_DIR}/scratch/gaussian_displacement_endpoint}"

cd "$NODE_DIR"
mkdir -p outputs

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

run_job() {
  local name="$1"
  local run_dir="${NODE_DIR}/outputs"
  local input="../inputs/${name}_endpoint_opt.gjf"
  local output="${name}_endpoint_opt.out"
  local log="${name}_endpoint_opt.runner.log"
  local driver="${name}_endpoint_opt.g16_driver.out"
  local metadata="run_metadata.${name}.txt"
  local scratch="${SCRATCH_ROOT}/${name}"
  local pid_file="${run_dir}/${name}_endpoint_opt.pid"

  if grep -q "Normal termination of Gaussian" "${run_dir}/${output}" 2>/dev/null; then
    echo "$(date -Is) $name already completed" | tee -a "${run_dir}/${log}"
    rm -f "$pid_file"
    return 0
  fi

  mkdir -p "$scratch" "$run_dir"
  (
    cd "$run_dir"
    export GAUSS_SCRDIR="$scratch"
    {
      echo "host=$(hostname)"
      echo "start=$(date -Is)"
      echo "run_dir=$run_dir"
      echo "input=$input"
      echo "output=$output"
      echo "driver=$driver"
      echo "g16=$G16"
      echo "GAUSS_SCRDIR=$GAUSS_SCRDIR"
    } > "$metadata"
    echo "$(date -Is) starting $name" | tee -a "$log"
    set +e
    "$G16" < "$input" > "$output" 2> "$driver"
    g16_status=$?
    set -e
    status="$g16_status"
    echo "g16_status=$g16_status" >> "$metadata"
    if [[ -s "$output" ]]; then
      echo "output_exists=true" >> "$metadata"
    else
      echo "output_exists=false" >> "$metadata"
      echo "error: expected Gaussian output missing or empty under outputs/: ${run_dir}/${output}" >&2
      echo "input=$input" >&2
      echo "run directory listing:" >&2
      ls -la >&2 || true
      if [[ "$g16_status" -eq 0 ]]; then
        status=91
      fi
    fi
    echo "end=$(date -Is)" >> "$metadata"
    echo "status=$status" >> "$metadata"
    echo "$(date -Is) finished $name status=$status" | tee -a "$log"
    exit "$status"
  ) &
  echo "$!" > "$pid_file"
}

run_job minus
run_job plus

status=0
for name in minus plus; do
  pid_file="outputs/${name}_endpoint_opt.pid"
  if [[ -f "$pid_file" ]]; then
    if ! wait "$(cat "$pid_file")"; then
      status=1
    fi
  fi
done

exit "$status"
