# TSPi Link 1

TSPi Link is the authenticated transport between TS Phone and an installation
Host. It carries the versioned `tspi-host/1` NDJSON stream; it is not Pi's
experimental remote protocol and it does not define research or session
ownership.

## WebSocket

Both Host and device connect to:

```text
wss://<relay>/v1/link
Sec-WebSocket-Protocol: tspi-link.v1
Authorization: Bearer <role-specific-token>
```

The Relay authenticates one Host or device and multiplexes device connections.
Control messages are strict JSON text frames:

```json
{"v":1,"type":"open","connectionId":"<uuid>","deviceId":"<uuid>","deviceName":"Phone"}
{"v":1,"type":"close","connectionId":"<uuid>","code":1000}
```

Host data frames contain a 16-byte connection UUID followed by one chunk of
opaque bytes. In the current default client those bytes are UTF-8 NDJSON
`tspi-host/1` requests and responses. The Relay preserves order and does not
parse, authorize, or deduplicate the application messages.

## Enrollment and pairing

Relay administrators create a short-lived Host enrollment code. The installation
redeems it once through `POST /v1/enrollments/redeem` and stores the returned
Host token in an owner-only file. An enrolled Host creates a short-lived Phone
pairing through `POST /v1/pairings`; the Phone redeems the single-use code and
receives a revocable device token.

`GET /v1/devices` and `DELETE /v1/devices/<device-id>` manage transport identity
only. Workspace and session authorization remains in the Host RPC layer.

## Security boundary

WSS protects Phone-to-Relay and Host-to-Relay traffic. Link 1 does not add
application-level end-to-end encryption, so a Relay operator can observe
forwarded Host RPC bytes. Deploy the Relay on trusted infrastructure and never
log tokens or payloads.
