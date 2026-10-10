# CoRAgent 0.18 installation layout

Only fresh standalone installations are supported. Installation-level `.pi/` and
`.agents/` trees are rejected. There is no legacy fallback, migration tool or
compatibility link.

```text
<install>/
  coragent             # sole public client, follows current
  uninstall.sh              # independent recovery/uninstall entry
  current -> releases/<id>  # sole active release selection
  releases/<id>/            # immutable application code and complete Skills
  runtimes/pi/<commit>/     # required pinned Pi dependency, not a cache
  runtimes/maintenance/     # recovery code independent of the active release
  etc/installation.json     # identity, environment store, workspace root, service
  etc/job.toml
  etc/email.toml
  etc/name-resolver.toml
  etc/pi/                   # Pi native settings, models and authentication
  etc/secrets/              # private SMTP and other credentials
  var/state/installation/   # installation receipts and Python manifests
  var/state/host/           # Host identity, receipts, leases and Monitor state
  var/state/pi/sessions/    # native SQLite session repository
  var/log/
  var/cache/                # safely rebuildable caches
  workspaces/               # default; an explicit external root is supported
```

No root `bin/` or public `coragentServer` is installed. Systemd invokes
`current/agent/libexec/coragent-host` with an explicit installation root.
Use `coragent --workspace <name>` for research, and
`systemctl --user … coragent.service` for service management.

Host Conda bases and wheel overlays live under
`~/soft/coragent/host-envs/<installation-id>/{base,kernels}/<hash>`. The installer
accepts `CORAGENT_HOST_ENV_ROOT` for a dedicated alternate store and persists it.
Scientific Job environments remain explicitly bound through `etc/job.toml`,
with separate local and remote paths. Existing Conda prefixes are not moved.

Sockets and process locks use the installation-scoped system runtime directory.
Durable receipts stay in state. The standard-library-only `research_agent.foundation.layout`
contract is shared by bootstrap, installers and the read-only doctor:

```bash
python3 scripts/app_layout_doctor.py --install-root /absolute/path --json
```

Default uninstall preserves configuration, credentials, sessions, workspaces and
Python environments. Explicit runtime removal requires an installation ownership
receipt and never removes shared scientific software. Fresh installation does
not restore archived sessions or replay old work. Workspace-local Pi files are
not installation state and are not removed by name matching.
