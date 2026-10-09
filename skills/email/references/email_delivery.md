# Delivery protocol

notification_id identifies one authorized delivery, never a retry time or note version. report_refs contains up to eight files under reports/ or artifacts/. prepare pins ts-user-notification/2, configured recipient, attachment hashes and sizes.

The send library locks logical identity, persists sending before transport and then records sent/failed/unknown. A failure proven to precede transport can retry under the same identity; reconcile uncertainty first. Password rotation does not bypass deduplication.

Receipts live under reports/email/deliveries. After sending, the CLI persists a runtime event using canonical receipt identity, then projects it into research records. Failed projections replay on the next research-context read without another email command. If event persistence itself fails, journal_error is visible and the send receipt remains authoritative; retry the same notification identity to recover registration without resending. Read a receipt through status --receipt-ref and record the outcome with research_update using the delivery Node and a note when such a Node exists.
