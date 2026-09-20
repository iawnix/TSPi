# TSPi Link 1

TSPi Link is the authenticated transport between TS Phone and the installation
Host. It does not define research, session, transcript, or tool operations;
those remain native Pi App Server services carried as opaque bytes.

## WebSocket

Both Hosts and devices connect to:

```text
wss://<relay>/v1/link
Sec-WebSocket-Protocol: tspi-link.v1
Authorization: Bearer <role-specific-token>
```

The bearer token identifies the connection as one Host or one device. A Host
has at most one active relay socket. Devices can connect only while their Host
is online.

Device sockets carry the native App Server byte stream directly. The Host
socket is multiplexed. Text messages are strict JSON control objects:

```json
{"v":1,"type":"open","connectionId":"<uuid>","deviceId":"<uuid>","deviceName":"Phone"}
{"v":1,"type":"close","connectionId":"<uuid>","code":1000}
```

Host binary messages contain a 16-byte connection UUID followed by one chunk
of the native App Server byte stream. Relays preserve chunk order and do not
decode the payload.

## Enrollment and pairing

Relay administrators create a short-lived Host enrollment code locally. A
TSPi installation redeems it once through `POST /v1/enrollments/redeem` and
stores the returned Host token in an owner-only file.

An enrolled Host creates a short-lived Phone pairing through
`POST /v1/pairings`. A Phone redeems the single-use code through
`POST /v1/pairings/redeem` and receives its own revocable device token.

Host-authenticated device management uses `GET /v1/devices` and
`DELETE /v1/devices/<device-id>`. These endpoints manage transport identity
only; they are not an alternate App Server API.

## Security boundary

WSS protects Phone-to-Relay and Host-to-Relay traffic. Link 1 does not add
application-level end-to-end encryption, so an operator of the Relay can
observe forwarded App Server bytes. Deploy the Relay on trusted infrastructure
or a private network. Tokens and message payloads must never be logged.
