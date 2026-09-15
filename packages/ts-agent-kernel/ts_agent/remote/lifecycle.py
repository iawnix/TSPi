"""Manifest-bound SSH + Torque lifecycle for TS calculations."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .client import SSHClient
from .errors import (
    RemoteCancellationAmbiguous,
    RemoteCommandError,
    RemoteError,
    RemotePreSubmitError,
    RemoteSubmissionAmbiguous,
    RemoteSubmissionRejected,
)
from .models import RemoteJobConfig, RemoteJobStatus, RemoteReceipt, TransferRecord
from .torque import (
    normalize_job,
    parse_program_status,
    parse_records,
    render_job_script,
    scheduler_semantics,
    validate_job,
    validate_job_id,
)
from .transfer import download_verified, ensure_directory, upload_verified


_RECEIPT_VALUE = re.compile(r"^[A-Za-z0-9_./:+ \[\]-]*$")


def submit(config: RemoteJobConfig, *, client: SSHClient | None = None) -> RemoteReceipt:
    try:
        validate_job(config)
        script = render_job_script(config)
        script_digest = submission_script_digest(config, rendered_script=script)
    except Exception as exc:
        raise RemotePreSubmitError("pre_submit_preparation", exc) from exc
    remote = client or SSHClient(config.profile)
    staged: list[TransferRecord] = []
    try:
        ensure_directory(remote, config.remote_dir)
    except Exception as exc:
        raise RemotePreSubmitError("ensure_directory", exc) from exc
    try:
        with tempfile.TemporaryDirectory(prefix="ts-remote-stage-") as temporary:
            script_path = Path(temporary) / config.script_name
            script_path.write_text(script, encoding="utf-8")
            staged.append(upload_verified(remote, script_path, config.remote_dir, config.script_name))
        seen = {config.script_name}
        for source in config.input_paths:
            if source.name in seen:
                raise RemoteError(f"remote input basename collision: {source.name}")
            seen.add(source.name)
            staged.append(upload_verified(remote, source, config.remote_dir, source.name))
    except Exception as exc:
        raise RemotePreSubmitError("upload", exc) from exc
    if {Path(item.remote_path).name for item in staged} & set(config.expected_artifacts):
        raise RemotePreSubmitError(
            "pre_submit_validation",
            RemoteError("expected artifacts overlap staged input names"),
        )

    submit_result = None
    submit_error: Exception | None = None
    try:
        submit_result = remote.run_script(
            _submit_script(),
            [
                config.remote_dir,
                config.submission_id,
                config.script_name,
                script_digest,
                config.profile.commands.qsub,
            ],
            check=False,
        )
    except Exception as exc:
        # Once the submission script is handed to SSH, transport failure cannot
        # prove that qsub was not invoked. Reconcile the durable record first.
        submit_error = exc
    try:
        record = read_submission_record(config, client=remote)
    except Exception as exc:
        raise RemoteSubmissionAmbiguous(
            {
                "state": "unknown",
                "phase": "submit_request_started",
                "error": str(submit_error or exc),
                "reconciliation_error": str(exc),
                "ssh_returncode": submit_result.returncode if submit_result is not None else None,
            }
        ) from exc
    state = record.get("state")
    if state == "rejected":
        raise RemoteSubmissionRejected(record)
    if state != "accepted":
        ambiguous = dict(record)
        ambiguous.setdefault("phase", "scheduler_result_unknown")
        raise RemoteSubmissionAmbiguous(ambiguous)
    return receipt_from_submission_record(config, record, script_digest=script_digest)


def submission_script_digest(
    config: RemoteJobConfig,
    *,
    rendered_script: str | None = None,
) -> str:
    script = rendered_script if rendered_script is not None else render_job_script(config)
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


def receipt_from_submission_record(
    config: RemoteJobConfig,
    record: dict[str, Any],
    *,
    script_digest: str | None = None,
) -> RemoteReceipt:
    if record.get("state") != "accepted":
        raise RemoteError("remote submission record is not accepted")
    job_id = validate_job_id(str(record.get("job_id", "")))
    expected_digest = script_digest or submission_script_digest(config)
    if (
        record.get("submission_id") != config.submission_id
        or record.get("script_sha256") != expected_digest
    ):
        raise RemoteError("remote submission receipt does not match the prepared calculation")
    submitted_at = record.get("updated_at")
    if not isinstance(submitted_at, str) or not submitted_at:
        raise RemoteError("remote submission record has no submission timestamp")
    return RemoteReceipt(
        schema_version="ts-remote-receipt/1",
        submission_id=config.submission_id,
        intent_id=config.intent_id,
        intent_digest=config.intent_digest,
        node_id=config.node_id,
        profile=config.profile.name,
        scheduler=config.profile.scheduler,
        scheduler_id=job_id,
        remote_dir=config.remote_dir,
        script_sha256=expected_digest,
        submitted_at=submitted_at,
        expected_artifacts=config.expected_artifacts,
    )


def read_submission_record(
    config: RemoteJobConfig,
    *,
    client: SSHClient | None = None,
) -> dict[str, Any]:
    remote = client or SSHClient(config.profile)
    text = remote.read_text(f"{config.remote_dir}/.ts-remote/submission.env", max_bytes=16 * 1024)
    record = _parse_record(text)
    if record.get("schema_version") != "ts-remote-submission/1":
        raise RemoteError("remote submission record has an invalid schema")
    if record.get("submission_id") != config.submission_id:
        raise RemoteError("remote submission record has a mismatched submission_id")
    return record


def status(
    config: RemoteJobConfig,
    job_id: str,
    *,
    client: SSHClient | None = None,
) -> RemoteJobStatus:
    validated = validate_job_id(job_id)
    remote = client or SSHClient(config.profile)
    program_text = remote.read_text(
        f"{config.remote_dir}/{config.program_status_name}",
        check=False,
        max_bytes=64 * 1024,
    )
    program = parse_program_status(program_text) if program_text.strip() else {}
    qstat = remote.run([config.profile.commands.qstat, "-f", validated], check=False)
    scheduler_state: str | None = None
    scheduler_exit: int | None = None
    scheduler_error: str | None = None
    if qstat.returncode == 0:
        jobs = parse_records(qstat.stdout, "Job Id")
        if jobs:
            if validated not in jobs:
                raise RemoteError("Torque status response is not bound to the requested job ID")
            scheduler = normalize_job(validated, jobs[validated])
            scheduler_state = scheduler.get("state")
            scheduler_exit = scheduler.get("exit_status")
        else:
            scheduler_error = "Torque returned no job record"
    else:
        scheduler_error = qstat.stderr.strip() or qstat.stdout.strip() or "Torque history unavailable"

    program_state = program.get("state")
    program_exit = _int_or_none(program.get("exit_status"))
    if program_state == "completed":
        state, program_status, error_class = "completed", "completed", None
    elif program_state == "failed":
        phase = program.get("phase")
        error_class = {
            "scratch_setup": "remote_scratch_failed",
            "activation": "remote_activation_failed",
        }.get(phase, "remote_program_failed")
        state, program_status = "failed", "failed"
    else:
        state, program_status, error_class = scheduler_semantics(scheduler_state, scheduler_exit)
        if scheduler_error and state == "unknown":
            error_class = "scheduler_history_unavailable"
    return RemoteJobStatus(
        state=state,
        program_status=program_status,
        job_id=validated,
        scheduler_state=scheduler_state,
        exit_status=program_exit if program_exit is not None else scheduler_exit,
        error_class=error_class,
        scheduler_query_error=scheduler_error,
        program_record=program,
    )


def tail(
    config: RemoteJobConfig,
    artifact: str,
    lines: int,
    *,
    client: SSHClient | None = None,
) -> str:
    remote = client or SSHClient(config.profile)
    result = remote.run(
        ["tail", "-n", str(max(1, lines)), "--", f"{config.remote_dir}/{artifact}"],
        check=False,
    )
    if result.returncode != 0 and result.stderr.strip():
        raise RemoteCommandError(
            "remote tail failed",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout


def collect(
    config: RemoteJobConfig,
    artifacts: list[str],
    output_dir: Path,
    *,
    client: SSHClient | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    remote = client or SSHClient(config.profile)
    downloaded: list[str] = []
    manifest: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in artifacts:
        # Historical CREST scripts captured stdout under the generic name.
        # Retain the real remote path/digest in the transfer receipt while
        # exposing the parser's stable local filename.
        remote_name = config.stdout_name if config.backend == "crest" and name == "crest.out" else name
        transfer = download_verified(remote, config.remote_dir, remote_name, output_dir / Path(name).name)
        downloaded.append(name)
        manifest.append(asdict(transfer))
    return downloaded, manifest


def cancel(
    config: RemoteJobConfig,
    job_id: str,
    *,
    client: SSHClient | None = None,
) -> dict[str, Any]:
    validated = validate_job_id(job_id)
    remote = client or SSHClient(config.profile)
    result = remote.run_script(
        _cancel_script(),
        [config.remote_dir, config.submission_id, validated, config.profile.commands.qdel],
        check=False,
    )
    try:
        record_text = remote.read_text(
            f"{config.remote_dir}/.ts-remote/cancellation.env",
            max_bytes=16 * 1024,
        )
        record = _parse_record(record_text)
    except Exception as exc:
        raise RemoteCancellationAmbiguous(
            "scheduler cancellation outcome is ambiguous; reconcile before retrying"
        ) from exc
    if (
        record.get("schema_version") != "ts-remote-cancellation/1"
        or record.get("submission_id") != config.submission_id
        or record.get("job_id") != validated
    ):
        raise RemoteCancellationAmbiguous("remote cancellation record is not bound to this job")
    if record.get("state") != "accepted":
        detail = record.get("error") or result.stderr.strip() or "qdel did not accept the request"
        raise RemoteError(str(detail))
    return record


def receipt_dict(receipt: RemoteReceipt) -> dict[str, Any]:
    value = asdict(receipt)
    value["expected_artifacts"] = list(receipt.expected_artifacts)
    return value


def _submit_script() -> str:
    return r'''set -euo pipefail
remote_dir=$1
submission_id=$2
script_name=$3
script_sha256=$4
qsub_command=$5
cd -- "$remote_dir"
install -d -m 700 -- .ts-remote
record=.ts-remote/submission.env
lock=.ts-remote/submit.lock
if ! mkdir -- "$lock" 2>/dev/null; then
  if [[ -s "$record" ]] && grep -qx 'state=accepted' "$record"; then exit 0; fi
  if [[ -s "$record" ]] && grep -qx 'state=rejected' "$record"; then
    rmdir -- "$lock" 2>/dev/null || true
    mkdir -- "$lock"
  else
    exit 75
  fi
fi
updated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
tmp="$record.tmp.$$"
printf '%s\n' 'schema_version=ts-remote-submission/1' "submission_id=$submission_id" \
  'state=started' "script_sha256=$script_sha256" "updated_at=$updated_at" > "$tmp"
mv -- "$tmp" "$record"
set +e
"$qsub_command" "$script_name" > .ts-remote/qsub.stdout.tmp 2> .ts-remote/qsub.stderr.tmp
rc=$?
set -e
mv -- .ts-remote/qsub.stdout.tmp .ts-remote/qsub.stdout
mv -- .ts-remote/qsub.stderr.tmp .ts-remote/qsub.stderr
updated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if [[ $rc -ne 0 ]]; then
  error=$(tr '\n=' '  ' < .ts-remote/qsub.stderr | cut -c1-1000)
  tmp="$record.tmp.$$"
  printf '%s\n' 'schema_version=ts-remote-submission/1' "submission_id=$submission_id" \
    'state=rejected' "script_sha256=$script_sha256" "qsub_exit=$rc" \
    "updated_at=$updated_at" "error=$error" > "$tmp"
  mv -- "$tmp" "$record"
  rmdir -- "$lock" 2>/dev/null || true
  exit 0
fi
job_id=$(tail -n 1 .ts-remote/qsub.stdout | tr -d '[:space:]')
case "$job_id" in ''|*[!A-Za-z0-9_.\[\]-]*) exit 76 ;; esac
tmp="$record.tmp.$$"
printf '%s\n' 'schema_version=ts-remote-submission/1' "submission_id=$submission_id" \
  'state=accepted' "script_sha256=$script_sha256" 'qsub_exit=0' "job_id=$job_id" \
  "updated_at=$updated_at" > "$tmp"
mv -- "$tmp" "$record"
'''


def _cancel_script() -> str:
    return r'''set -euo pipefail
remote_dir=$1
submission_id=$2
job_id=$3
qdel_command=$4
cd -- "$remote_dir"
install -d -m 700 -- .ts-remote
record=.ts-remote/cancellation.env
lock=.ts-remote/cancel.lock
if ! mkdir -- "$lock" 2>/dev/null; then
  if [[ -s "$record" ]] && grep -qx 'state=accepted' "$record"; then exit 0; fi
  exit 75
fi
updated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
tmp="$record.tmp.$$"
printf '%s\n' 'schema_version=ts-remote-cancellation/1' "submission_id=$submission_id" \
  "job_id=$job_id" 'state=started' "updated_at=$updated_at" > "$tmp"
mv -- "$tmp" "$record"
set +e
"$qdel_command" "$job_id" > .ts-remote/qdel.stdout.tmp 2> .ts-remote/qdel.stderr.tmp
rc=$?
set -e
mv -- .ts-remote/qdel.stdout.tmp .ts-remote/qdel.stdout
mv -- .ts-remote/qdel.stderr.tmp .ts-remote/qdel.stderr
updated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
if [[ $rc -eq 0 ]]; then state=accepted; else state=rejected; fi
error=$(tr '\n=' '  ' < .ts-remote/qdel.stderr | cut -c1-1000)
tmp="$record.tmp.$$"
printf '%s\n' 'schema_version=ts-remote-cancellation/1' "submission_id=$submission_id" \
  "job_id=$job_id" "state=$state" "qdel_exit=$rc" "updated_at=$updated_at" \
  "error=$error" > "$tmp"
mv -- "$tmp" "$record"
'''


def _parse_record(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in text.splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", key) or "\x00" in value or any(
            ord(character) < 32 and character not in "\t" for character in value
        ):
            raise RemoteError("remote control record contains invalid data")
        if key != "error" and not _RECEIPT_VALUE.fullmatch(value):
            raise RemoteError("remote control record contains an invalid bounded value")
        if key in result:
            raise RemoteError("remote control record contains duplicate fields")
        result[key] = value
    return result


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
