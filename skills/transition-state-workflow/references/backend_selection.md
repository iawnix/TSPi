# Backend Selection

Choose strategy from the chemistry hypothesis first, then choose a backend.

Common strategy layers:

- conformer or pose generation for plausible endpoints;
- relaxed scan or string/NEB for reaction-coordinate discovery;
- TS optimization and frequency validation for saddle-point evidence;
- displacement, endpoint optimization, or IRC for connectivity evidence;
- higher-level refinement when lower-level evidence is promising.

Backend selection should be documented in the node rationale. Backend failure is
an execution fact, not a chemistry verdict.
