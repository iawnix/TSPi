# CoRAgent 0.19 identity cutover

This is a breaking release, not an in-place branding update. The supported
combination is CoRAgent 0.19 and CoRHub 0.20. Neither release is implied to be
published by the presence of this document.

| Surface | New identity |
| --- | --- |
| Repository | `iawnix/coragent` |
| CLI / optional web CLI | `coragent` / `coragent-web` |
| npm / Python distribution | `@iawnix/coragent` / `coragent` |
| Internal Python imports | `research_agent` (unchanged) |
| Configuration environment | `CORAGENT_*` |
| Host / Relay / Web services | `coragent.service` / `coragent-relay.service` / `coragent-web.service` |
| Host / Link protocol | `coragent-host/2` / `coragent-link.v1` |
| Host / device token | `cah_` / `cad_` |

No old command aliases, protocol negotiation, configuration fallback or old
installation-schema readers are provided. Protocol version numbers retain their
meaning; the namespace change itself is an incompatible identity change.

## Existing deployments

1. Finish or explicitly stop active research and scientific jobs. Back up the
   old installation, external workspace roots, Relay database and configuration
   together. Keep credentials private. Record the old service units and versions.
2. Stop the old Host, Web and Relay services using their actual installed unit
   names. Use the old release's uninstaller to remove its services and entrypoints
   while retaining data. The new uninstaller owns only the new installation.
3. Install CoRAgent in a fresh directory with a fresh Relay state directory.
   Recreate configuration using the current templates and `CORAGENT_*` variables.
   Do not copy old installation markers, release pointers or environment receipts
   into the new root. Absolute paths are part of installation ownership checks.
4. Enroll the Host with the new Relay, install the matching CoRHub and run
   `coragent phone pair`. Pair every device again. Changing a token prefix cannot
   migrate authentication; tokens must be issued by the new Relay.
5. Verify a new workspace, session, message, reconnect and Monitor operation
   before resuming production work. Confirm only the intended new services run.

Existing research files are not deleted or rewritten by this source change.
The release does not provide an automatic import of old catalogs, sessions or
installation state. Do not rename/move a live workspace: its manifest binds its
absolute path. Retaining a backup is not equivalent to validating an import.
Any required historical-state conversion must be performed offline on a copy,
validated separately, and must not be implemented as a runtime fallback reader.

## Rollback

Stop and uninstall the new services with the new release's tools, retaining any
new research separately. Restore the old program, configuration and matching
data backup as one set, with the corresponding old client. Never point an old
release at state written by the new release or overwrite newer research with
an older backup.

Repository URLs change independently of deployment paths. The local checkout
and the mandated private test root `/home/iaw/project/TSPi/local_debug` stay in
place; test data is never published or bundled with releases.
