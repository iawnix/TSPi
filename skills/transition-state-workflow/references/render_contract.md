# Render Contract

`ts_subagent_render` creates one bounded local visualization. It starts a fresh
operator session with exactly one path-bound render tool; it does not perform
scientific Review.

## Public Operations

- `render`: one structure to PNG or JPEG;
- `compare`: multiple structures to one comparison image;
- `animate`: one trajectory to GIF;
- `mechanism`: reactant/TS/product structures to one mechanism image.

The request supplies one owning `nodeId`, 1 to 8 existing workspace-relative
`inputRefs`, and one new `outputRef` under
`nodes/<nodeId>/outputs/`. The host rejects absolute paths, parent traversal,
symlink components, missing inputs, cross-Node output ownership, unsupported
extensions, and overwrite.

`xyzrender` is the only render backend. Blender, FFmpeg, OpenBabel, Mayavi, and
PyVista are neither required nor probed.

## Authority

Render may read the declared structures or trajectories and create only the
declared image or animation. It must not:

- edit canonical workspace files;
- change a Claim or evaluate a Gate;
- close a Node or accept a TS/pathway;
- infer mechanism validity, stereochemistry, connectivity, or electronic state
  from visual appearance;
- send the artifact externally.

The host checks that a nonempty bound output exists before it reports success.
The render journal and image are operational artifacts. A rendered picture is
not scientific Evidence by itself.

## Workspace Recording

Keep the render run under the owning Node and, when useful, link its immutable
operation ref through a normal `update_workspace` Decision. Do not register
`render_completed=true` as scientific support merely to expose the file.

If the Root Agent extracts a real scientific observation, such as a declared
stereochemical mismatch, verify that observation against the source coordinates
with an appropriate deterministic comparator or explicit manual observation.
Then draft normal Evidence from the source artifact and provenance, omit the
Kernel-owned `evidence_id`, validate the Decision, and apply it unchanged.

The maintenance CLI under `scripts/ts_render.py` wraps the same deterministic
renderer, but ordinary research sessions should use the registered public tool
and its schema rather than discovering calls from implementation scripts.
