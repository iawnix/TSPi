# TSPi Session Control Contract

`tspi-session-control/1` is the transport-neutral command contract for one
Pi App Server session. The App Server remains the only owner of the session,
agent lane, transcript, and workspace Root lock. A client may carry these
messages over TSPi Link (the TS Phone path) or the optional local HTTP/SSE
adapter in `apps/app-server/pi-session-control-server.mjs` (the browser path).

The contract deliberately has no scientific state or workspace file writes.
`AgentController` is the authority for prompt admission, busy responses,
queueing, and aborts. `Transcript` is the authority for ordered session
events. Clients must treat `request_id` as an idempotency key and must not
resubmit a request after reconnect unless the same request id and payload are
used. A repeated request id with a different payload is a protocol error.

## Request lifecycle

1. Attach to a session through Pi's `SessionManagement` service.
2. Fetch or receive a snapshot and remember its `cursor`.
3. Submit `prompt`, `queue`, or `abort` with a fresh `request_id`.
4. Subscribe to events from the remembered cursor. The first event after every
   reconnect is a coherent `snapshot`; later events have monotonically
   increasing `sequence` values.
5. On a sequence gap, discard the local session cache and request a new snapshot.

The optional Web adapter is intentionally a thin transport. It does not start
Pi, create workers, or introduce a second session broker. TS Phone uses the
native Pi App Server byte stream through TSPi Link.

## HTTP adapter routes

When enabled by an operator, the adapter exposes one attached session:

| Method | Route | Meaning |
| --- | --- | --- |
| `GET` | `/health` | protocol and attached-session readiness |
| `GET` | `/v1/session/{session_id}/snapshot` | coherent snapshot and cursor |
| `POST` | `/v1/session/{session_id}/requests` | one control request JSON body |
| `GET` | `/v1/session/{session_id}/events?after_sequence=N` | SSE snapshot/event stream |

The adapter binds loopback by default. A non-loopback bind requires a bearer
token. Deployments that expose it outside localhost must also provide TLS and
an origin policy.

For a local browser adapter, attach it to the already-running Host with:

```bash
TSPi gateway \
  --connect /run/user/$UID/tspi/<server-id>.sock \
  --session-id <session-id> \
  --port 8767
```

This command exits if the Host cannot be reached or the session is not
available. It does not start a Host and it does not create a session.
