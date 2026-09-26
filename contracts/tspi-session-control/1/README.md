# TSPi Session Control Contract

`tspi-session-control/1` is a compatibility contract for the optional browser
adapter. The current source of truth for Phone and Host clients is
`tspi-host/1` (`apps/app-server/tspi-host.mjs`); this contract gives a browser a
stable, session-bound HTTP shape without creating another Pi runtime.

The Pi App Server `SessionWorker`/`AgentHarness` lane is the owner of the agent
loop, transcript, model, tools, and workspace lock. This adapter only attaches
to an existing Host session. It must never start Pi, execute client-supplied
extensions, or write scientific files directly.

## Request lifecycle

1. Attach to one existing session and fetch `session/read` as a coherent snapshot.
2. Keep the returned `epoch` and `sequence` watermark.
3. Submit `input/send`, `turn/interrupt`, or a supported Monitor operation with
   an idempotent `request_id`; input also requires `client_message_id`.
4. Reconnect by fetching a new snapshot. A request whose outcome is uncertain
   is not automatically replayed.
5. Treat `accepted` as admission to Pi, not as completion of the agent turn.

## HTTP adapter routes

The adapter binds loopback by default. A non-loopback bind requires a bearer
token and an explicit origin policy.

| Method | Route | Meaning |
| --- | --- | --- |
| `GET` | `/health` | protocol and attached-session readiness |
| `GET` | `/v1/session/{session_id}/snapshot` | Host `session/read` result |
| `POST` | `/rpc` | allowlisted Host RPC method and params |
| `POST` | `/v1/session/{session_id}/requests` | compatibility prompt/abort translation into Host RPC |
| `GET` | `/v1/session/{session_id}/events` | SSE snapshot and Host notifications |

The adapter binds workspace and session from its startup arguments, rejects
cross-session parameters and unsolicited browser origins, bounds request and
SSE buffers, and closes when its Host connection closes.

Example:

```bash
node apps/app-server/tspi-browser-gateway.mjs \
  --connect unix:///run/user/$UID/tspi/<server-id>.sock \
  --workspace /absolute/workspaces/reaction-a \
  --session-id <session-id> --port 8767
```

This command exits if the Host or session is unavailable. It does not create a
session or start a worker.
