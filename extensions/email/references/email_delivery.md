# Delivery request and recovery

The draft contains `notification_id` (stable user-request/event/report identity), `event`, `subject`, `summary`, and `report_refs` (up to eight workspace-relative reports/ or artifacts/ files). Research workspaces also require the delivery `node_id`. `prepare` binds schema ts-user-notification/2, configured recipient, attachment digests and sizes, plus `state_binding` for the reported scope. Prepare a new version for a changed report or consumed state.

Declare the delivery Node's scope with `consumes.requirement_ids`, `consumes.artifact_refs`, typed `dependencies`, or a combination. An empty declaration does not establish an independent notification. `consumes.condition` defaults to `satisfied`; use `observed` for an authorized update about unmet work. Artifact selection names the actual registered evidence, not report paths. `report_refs` identifies attachments separately. Machine-produced material must belong to its producer's current collected result, including derivation inputs.

| Event | State assertion checked at preparation and first send |
| --- | --- |
| `progress` | Report the declared scope at its recorded state; use `observed` for unmet requirements. |
| `node_completed` | Every explicitly declared predecessor is closed/completed. This does not assert whole-study acceptance. |
| `calculation_failed` | A consumed Attempt is confirmed failed or timed out. An unrelated failure is insufficient. |
| `calculation_ambiguous` | A consumed Attempt is unknown or has an execution conflict. |
| `study_completed` | All tracked user requirements are currently satisfied; observed/untracked scope cannot establish study success. |

For a success delivery, use e.g. `consumes: {requirement_ids: ["requirement_path"]}` with a `completed` predecessor. For an authorized failure notice, use `consumes: {requirement_ids: ["requirement_path"], condition: "observed"}` and `dependencies: [{node_id: "node_ts", condition: "finished"}]`. A finished predecessor must actually be closed; blocked is not a terminal outcome. Keep the original failed/inconclusive outcome. A request for final results alone does not authorize these failure notices.

The binding includes consumed source Node states, requirement assessments, selected Artifact versions and producing result receipts. A source change rejects the old prepared request. Read the changed scope and prepare again; do not manually edit a binding or force a Node to completed. A progress request prepared before predecessor completion must be prepared again after that predecessor closes. `node_completed` cannot be prepared while its assertion is still false. After a successful send, replay the original request to recover its receipt instead of preparing a new identity.

The installation retains TLS settings and credential references. `check --root ... --output ...` validates configuration without sending. Credentials never belong in command arguments, requests or report files. The send command revalidates attachments and recipient before contacting the transport.

The send library retains locked receipts under reports/email/deliveries. A stable identity deduplicates retries across bash invocations and unrelated research revisions. Password rotation does not authorize resending. A legacy receipt with the same event and subject requires reconciliation before a new-format send because old receipts cannot prove complete content identity. Keep these receipts when upgrading or rolling back.

After SMTP DATA or a worker crash, delivery may be unknown. SMTP does not provide a universal status-query API; a deterministic Message-ID is not exactly-once delivery. Read the saved receipt and use a transport status query only when actually supported. Do not automatically retry sent, sending or unknown requests. Confirmed pre-delivery failures can be retried after fixing the cause. Sender acceptance is not proof of inbox delivery.

Before a new send, the Node must have completion conditions, the required strategy, satisfied typed dependencies and State admission. A finished edge does not bypass a global blocked/terminal lifecycle. Use a criterion such as “registered receipt confirms transport accepted the authorized report”; sent means transport acceptance only. Register the actual durable receipt path returned by send, then cite its artifact_ref or artifact_id in evaluate_gate.evidence_refs. The receipt preserves the binding that was admitted. No calculation Attempt is created.

The sender serializes notification_id across processes. Identical content reuses a sent receipt; changing content under that identity is rejected. Unexpected errors after entering transport, a leftover sending receipt, or legacy delivery_failed receipts require reconciliation. They are not proof that no message was sent.
