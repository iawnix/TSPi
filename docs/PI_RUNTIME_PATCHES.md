# Managed Pi runtime patches

TSPi pins Pi v1.0.4 at `7c10bd4337495ee613f2224843ecdf349b80d1df`
in `config/pi-source.json`. The experimental transport protocol remains version 9.
Terminal presentation uses Pi's experimental client, separately from ordinary
`InteractiveMode`.

`scripts/prepare_pi_source.py` preflights the ordered patches in
`config/pi-patches/`, skips completely applied groups, and rejects partial or
incompatible groups before applying pending changes. Verification checks that
Git can reverse every patch; comments or version strings alone are insufficient.
A mismatched upstream commit is rejected. Keep the patch groups independent so
all pending patches can be checked before changing files.

| Patch | Purpose | Validation |
|---|---|---|
| 001-workspaces | Workspace-scoped catalog directories, metadata, cwd, and ambiguous ID rejection | Native worker startup, Host routing, existing SQLite session recovery |
| 002-worker-launch | TSPi worker entry and stderr diagnostics | Native worker startup and terminal diagnostics |
| 003-client-connection | Observe connection and attachment state for Unix as well as Radius | Pi client tests and native connection tests |
| 004-client-lifecycle | AbortSignal closes only the presentation; Host-selected sessions must already exist | Session switching, quit, missing-session rejection, connection disposal |
| 005-client-history | Populate input history from accepted user entries in the active transcript | Pi presentation/history tests; each session gets a new editor |

Application integration lives outside these patches. The worker publishes the
`tspi.client-queries` service, bound to its workspace, session, kernel bridge, and
prompt manifest. The terminal consumes it through Pi's attached session service
source, including over SSH. No client-side Python process reads research state.
The slash registry is defined in `command_catalog.json`; Pi owns its editor,
selectors, transcript, model commands, and input loop.

`/resume` asks the Host for an available session in the current workspace, then
closes and recreates only the terminal presentation. `/quit` disconnects only the
terminal. SSH connections proxy both the Host and Pi sockets; proxies and their
SSH children are closed when the terminal exits.

## Updating Pi

Prepare a separate checkout under the configured test environment. Validate the
patch groups, real worker queries, presentation, session recovery, Host/Phone/
Monitor contracts, and packaging before updating the source pin and npm lock.
Source pin and Pi package versions must move together. Use a new managed runtime
directory for a new commit; existing session directories retain their layout.

Pi 1.0.3 renamed the Azure provider from `azure-openai-responses` to `azure`.
Installations using Azure must update that provider key in authentication, model,
and settings configuration when moving from 1.0.2 to 1.0.4. The corresponding
`AZURE_OPENAI_*` environment variables are unchanged. This upgrade does not add
ordinary Pi's full command set to the experimental TUI.

Monitor admission is implemented in TSPi's worker service rather than another
Pi source patch. `monitor-admission.mjs` uses the pinned
`packages/durable/src/harness/submissions.ts` transaction primitive
`admitSubmission`: checking the run/inbox, reassessing Research State and placing
input must share one Pi commit. Native tests cover busy rejection, batch
idempotency, concurrent native input and obsolete legacy queue removal. Recheck
this internal API on every Pi pin update.
