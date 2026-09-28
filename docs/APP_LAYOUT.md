# Research Agent Application Layout

Research Agent is an application with a private Pi adapter. The supported
target layout is:

```text
<install>/
  bin/                  # stable entrypoint shims
  releases/<id>/       # immutable application releases
  current -> releases/<id>
  etc/                  # configuration and owner-only secrets
  var/                  # workspaces, sessions, artifacts, logs and locks
```

The current installer still supports the historical
`<install>/.pi/packages/tspi` layout. It is a migration source, not a second
state authority. Do not copy files or create a second `current` pointer by
hand. Inspect an installation before migration:

```bash
python3 scripts/app_layout_doctor.py --install-root /absolute/path --json
```

The doctor is read-only. A `mixed` result means both layouts exist and must be
resolved by an explicit migration procedure; no launcher or installer should
silently merge their release, session, or workspace state. An `unmarked`
standalone-looking tree is also rejected until its owner writes the marker
`etc/research-agent-layout.json` after preparing all directories.
