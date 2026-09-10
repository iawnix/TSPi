---
name: tspi-email
description: Deliver fixed-target, receipt-bound TSPi research notifications without exposing credentials or changing scientific state.
---

# TSPi Email Notifications

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `ts_notify` and configured email delivery. Load
`tspi-orchestration` for operational, report, artifact, and state contracts.
Notifications communicate recorded outcomes; they do not create or mutate
scientific state.

## Operating Rules

- Read the installation-owned notification configuration and use its fixed
  recipient; Root-provided subject or summary text cannot redirect delivery.
- Allow only the versioned event types and exact report-package members defined
  by the delivery contract.
- Treat a delivery receipt as operational provenance. It is not an Observation,
  Finding, acceptance record, or proof of scientific correctness.
- Keep known success idempotent and leave ambiguous delivery unresolved rather
  than replaying it automatically.
- Never place credentials, private tokens, or authentication URLs in workspace
  state, prompts, reports, or notification bodies.

Read `references/email_delivery.md` for the request shape, attachment rules,
receipt identity, and failure semantics.
