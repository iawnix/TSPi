# Security Policy

## Supported Versions

Security fixes target the latest revision on `main` and the latest published
TSPi release. Older releases may not receive fixes for the Host, Link Relay,
Native Pi Harness, or workspace formats.

## Reporting A Vulnerability

Please do not open a public issue for an exploitable vulnerability. Use a
private GitHub security advisory for this repository, or contact the
maintainer through the private channel listed on the repository profile.

Include the affected revision, deployment mode, a minimal reproduction, impact,
and any logs with credentials or workspace data removed. Do not send SMTP
authorization codes, SSH keys, model tokens, or private research artifacts.

The maintainer will acknowledge a report when received, coordinate a fix or
mitigation, and publish a release note after users have a remediation path.

## Deployment Notes

Keep `.pi` state, `compute.toml`, notification configuration, and Host sockets
owner-readable. Bind browser control to loopback unless a reviewed gateway
authentication and origin policy is in place. Treat remote compute hosts and
Link Relay infrastructure as trusted boundaries and rotate credentials after
an incident.
