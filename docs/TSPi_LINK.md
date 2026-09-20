# TSPi Link

[English](TSPi_LINK.md) | [简体中文](TSPi_LINK.zh-CN.md)

TSPi Link connects TS Phone to an installation Host without exposing the App
Server. It is a transport boundary, not a second application server:

```text
TS Phone -- WSS --> TSPi Link Relay <-- WSS -- TSPi Host -- Unix socket -- App Server
```

The Relay owns Host enrollment, Phone pairing, device revocation, and opaque
byte forwarding. The App Server remains the sole owner of workspaces, sessions,
transcripts, models, tools, ResearchMap, and compute state.

## Install TSPi Link Relay

TSPi Link Relay is a standalone service for a public or privately reachable
machine. It is not installed by the local TSPi Host installer. From a TSPi
checkout on the Relay machine:

```bash
./install-link-relay.sh \
  --public-url https://link.example.com \
  --listen 127.0.0.1 --port 8788 \
  --service-scope system --enable-services --start-services
```

The installer creates `tspi-link-relay.service`, installs the locked npm
runtime below its private installation root, stores SQLite state under
`/var/lib/tspi-link-relay`, and prints a single-use Host enrollment code.
Install the TLS reverse proxy separately in front of the loopback listener.
The proxy must preserve WebSocket upgrades and request bodies, must not log
`Authorization` headers or Link payloads, and should rate-limit enrollment and
pairing endpoints.

The public URL must be HTTPS; plain HTTP is accepted only for loopback
development.

To remove the standalone service, stop and unregister its unit while keeping
enrolled Host and device credentials by default:

```bash
./uninstall-link-relay.sh --service-scope system --non-interactive --yes
```

Add `--purge-state` only when the Relay database and all enrolled credentials
should also be deleted.

## Enroll A Host

The standalone installer prints a ten-minute, single-use enrollment code. To
create another code later, run the installed CLI:

```bash
node /opt/tspi-link-relay/current/service/cli.mjs enrollment create \
  --state /var/lib/tspi-link-relay/relay.db
```

Run the TSPi installer on the Host, select `TSPi Link Relay` Phone access, and enter
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
