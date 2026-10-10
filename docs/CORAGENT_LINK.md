# CoRAgent Link

[English](CORAGENT_LINK.md) | [简体中文](CORAGENT_LINK.zh-CN.md)

CoRAgent Link connects CoRHub to an installation Host without exposing a public
Pi or Host socket. It is a transport boundary, not a second application server:

```text
CoRHub -- WSS --> CoRAgent Link Relay <-- WSS -- CoRAgent Host -- Unix socket -- Pi App Server / Harness
```

The Relay owns Host enrollment, Phone pairing, device revocation, and opaque
frame forwarding. The Host owns routing and client access; the Pi Harness
worker owns sessions, transcripts, models, and tools. The Relay never owns
workspaces, research map, or compute state.

## Install CoRAgent Link Relay

CoRAgent Link Relay is a standalone service for a public or privately reachable
machine. It can be installed separately, or together with a Host using `--with-link-relay`.
From a CoRAgent checkout on the Relay machine:

```bash
./install.sh relay --source local \
  --public-url https://link.example.com \
  --listen 127.0.0.1 --port 8788 \
  --service-scope system --enable-services --start-services
```

The installer creates `coragent-relay.service`, installs the locked npm
runtime below its private installation root, stores SQLite state under
`/var/lib/coragent-relay`, and prints a single-use Host enrollment code.
Install the TLS reverse proxy separately in front of the loopback listener.
The proxy must preserve WebSocket upgrades and request bodies, must not log
`Authorization` headers or Link payloads, and should rate-limit enrollment and
pairing endpoints.

The public URL must be HTTPS; plain HTTP is accepted only for loopback
development.

To remove the standalone service, stop and unregister its unit while keeping
enrolled Host and device credentials by default:

```bash
./uninstall.sh relay --service-scope system --non-interactive --yes
```

Add `--purge-state` only when the Relay database and all enrolled credentials
should also be deleted.

## Enroll A Host

The standalone installer prints a ten-minute, single-use enrollment code. To
create another code later, run the installed CLI:

```bash
node /opt/coragent-relay/current/services/relay/cli.mjs enrollment create \
  --state /var/lib/coragent-relay/relay.db
```

Run the CoRAgent installer on the Host, select `CoRAgent Link Relay` Phone access, and enter
the Relay URL and enrollment code. The installer stores the Host credential in
`var/state/host/host.token` with owner-only permissions. The Host service
then maintains the outbound Link connection automatically.

## Pair And Revoke Phones

On the enrolled Host:

```bash
coragent phone pair
coragent phone devices
coragent phone revoke <device-id>
```

Enter the Relay URL and eight-character pairing code in CoRHub. The code
expires after five minutes and works once. Each Phone receives a separate
device token, so revoking one device does not rotate Host or other device
credentials. Revocation closes an active device socket immediately.

## Security Boundary

Host and device tokens are random 256-bit values stored as SHA-256 hashes by
the Relay. Long-lived tokens are never put in pairing codes or systemd
environment variables. WSS protects both network legs, but Link 1 does not add
application-level end-to-end encryption. A Relay operator can observe the
forwarded `coragent-host/2` NDJSON bytes, so use trusted infrastructure or a private
network.

The wire contract is documented in
[`contracts/link/1/README.md`](../contracts/link/1/README.md).
