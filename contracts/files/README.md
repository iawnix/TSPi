# Workspace files v1

The phone uses `files/list`, `files/stat`, `files/read`, and `files/pin` capabilities over the
existing authenticated `coragent-host/2` / Link connection. No public download
URL or separate filesystem authority is introduced. Reads do not wake a model.

All methods require `workspace_id`. `path` is a slash-separated relative path;
only listing may use the empty root. Allowed roots are inputs, artifacts, runs,
reports and outputs. Hidden paths, links, hard-linked files, special files and
non-material extensions are excluded by the server, not just by the UI.
The extension allowlist lives in `application/workspace_files.py`.

* `files/list`: `path`, optional `limit` (1–100), opaque `cursor`. Returns
  `{schema_version: "coragent-files/1", items: File[], next_cursor}`.
* `files/stat`: `path`. Returns `{file, max_chunk_bytes, max_preview_bytes}`.
* `files/read`: `path`, `expected_version`, `offset`, `length` (1–65536).
  Returns `{file, offset, data_base64, next_offset, eof}`. The client requests
  the next chunk only after consuming the last and can stop between requests.

`File = {path, name, kind: "directory" | "file", size, version}`. Versions are
opaque identity/change tokens, not content digests or immutable Artifacts.
A changed directory cursor or file returns `file_changed`; restart explicitly.
A preview is capped at 8 MiB. Small bounded range responses avoid embedding
files in chat messages, and yield between chunks so controls remain responsive.
`files/pin` takes `path` and `expected_version`. Explicitly adding a file to a
phone draft captures up to 8 MiB into `inputs/phone-references/<sha256>.<ext>`
with atomic replacement and read-only permissions. It returns `path`,
`source_path`, `source_version`, `sha256`, `size`. Retrying the same source
version/content addresses the same snapshot; it does not duplicate a job or
submit a model request. Source changes require opening the file again.

The phone stores a JSON file reference (and optional atom selection) in the
existing text draft, displayed as a removable file chip with inspectable details.
The wire form appends `[CoRHub file]` followed by a JSON code block. Only an explicit send submits it through the
existing durable `input/send`/outbox path. File bytes are never put into chat.
The agent can read the captured workspace material using its existing tools.
This is a file snapshot, not a Research Memory Artifact or a new message type.
Uploads, arbitrary writes and scientific edits remain outside this contract.
