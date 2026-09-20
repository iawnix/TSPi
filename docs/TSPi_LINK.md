# TSPi Link

[English](TSPi_LINK.md) | [简体中文](TSPi_LINK.zh-CN.md)

TSPi Link connects TS Phone to an installation Host without exposing the App
Server. It is a transport boundary, not a second application server:

```text
TS Phone -- WSS --> TSPi Relay <-- WSS -- TSPi Host -- Unix socket -- App Server
```

The Relay owns Host enrollment, Phone pairing, device revocation, and opaque
byte forwarding. The App Server remains the sole owner of workspaces, sessions,
transcripts, models, tools, ResearchMap, and compute state.

## Run A Relay

Install the Relay's pinned dependency and keep its state outside the source
checkout:

```bash
npm --prefix services/tspi-relay ci
node services/tspi-relay/cli.mjs serve \
  --state /var/lib/tspi-relay/relay.db \
  --public-url https://link.example.com \
  --listen 127.0.0.1 --port 8788
```

Put a TLS reverse proxy in front of the loopback listener. It must preserve
WebSocket upgrades and request bodies, and it must not log `Authorization`
headers or Link payloads. Apply request-rate limits to the enrollment and
pairing endpoints. The public URL must be HTTPS; plain HTTP is accepted only
for loopback development.

## Enroll A Host

Create a ten-minute, single-use enrollment code on the Relay machine:

```bash
node services/tspi-relay/cli.mjs enrollment create \
  --state /var/lib/tspi-relay/relay.db
```

Run the TSPi installer on the Host, select `TSPi Relay` Phone access, and enter
the Relay URL and enrollment code. The installer stores the Host credential in
`.pi/app-server-host/host.token` with owner-only permissions. The App Server
service then maintains the outbound Link connection automatically.

## Pair And Revoke Phones

On the enrolled Host:

```bash
TSPi phone pair
TSPi phone devices
TSPi phone revoke <device-id>
```

Enter the Relay URL and eight-character pairing code in TS Phone. The code
expires after five minutes and works once. Each Phone receives a separate
device token, so revoking one device does not rotate Host or other device
credentials. Revocation closes an active device socket immediately.

## Security Boundary

Host and device tokens are random 256-bit values stored as SHA-256 hashes by
the Relay. Long-lived tokens are never put in pairing codes or systemd
environment variables. WSS protects both network legs, but Link 1 does not add
application-level end-to-end encryption. A Relay operator can observe the
forwarded App Server bytes, so use trusted infrastructure or a private network.

The wire contract is documented in
[`contracts/tspi-link/1/README.md`](../contracts/tspi-link/1/README.md).
