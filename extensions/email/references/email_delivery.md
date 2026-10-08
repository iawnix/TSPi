# Delivery request and recovery

The draft contains `notification_id` (stable user-request/event/report identity), `event` (progress, node_completed, calculation_failed, calculation_ambiguous, study_completed), `subject`, `summary`, and `report_refs` (up to eight workspace-relative reports/ or artifacts/ files). `prepare` binds schema ts-user-notification/2, configured recipient, attachment digests and sizes. Do not edit prepared inputs after approval/authorization; prepare a new version for a changed report.

The installation retains TLS settings and credential references. `check --root ... --output ...` validates configuration without sending. Credentials never belong in command arguments, requests or report files. The send command revalidates attachments and recipient before contacting the transport.

The send library retains locked receipts under reports/email/deliveries. A stable identity deduplicates retries across bash invocations and unrelated research revisions. Password rotation does not authorize resending. A legacy receipt with the same event and subject requires reconciliation before a new-format send because old receipts cannot prove complete content identity. Keep these receipts when upgrading or rolling back.

After SMTP DATA or a worker crash, delivery may be unknown. SMTP does not provide a universal status-query API; a deterministic Message-ID is not exactly-once delivery. Read the saved receipt and use a transport status query only when actually supported. Do not automatically retry sent, sending or unknown requests. Confirmed pre-delivery failures can be retried after fixing the cause. Sender acceptance is not proof of inbox delivery.

In research workspaces add `node_id` to the draft. The Node must have completion conditions, an active strategy, and completed dependencies before a new send. Use a criterion such as “registered receipt confirms transport accepted the authorized report”; sent means transport acceptance only. Register the actual durable receipt path returned by send, then cite its artifact_id in evaluate_gate.evidence_refs. No calculation Attempt is created.

The sender serializes notification_id across processes. Identical content reuses a sent receipt; changing content under that identity is rejected. Unexpected errors after entering transport, a leftover sending receipt, or legacy delivery_failed receipts require reconciliation. They are not proof that no message was sent.
